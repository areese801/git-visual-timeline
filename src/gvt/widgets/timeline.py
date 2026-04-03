"""Timeline widget for gvt."""

from __future__ import annotations

from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from rich.text import Text

from gvt.git.repo import CommitInfo


class CursorMoved(Message):
    """Posted when cursor position changes."""

    def __init__(self, left_idx: int, right_idx: int) -> None:
        self.left_idx = left_idx
        self.right_idx = right_idx
        super().__init__()


# Tokyo Night heatmap colors
COLOR_GREEN = "#9ece6a"
COLOR_AMBER = "#e0af68"
COLOR_RED = "#f7768e"
COLOR_CURSOR = "#7aa2f7"
COLOR_PIN_START = "#7aa2f7"
COLOR_PIN_END = "#bb9af7"
COLOR_RANGE = "#283457"
COLOR_DIM = "#565f89"
COLOR_BG = "#1a1b26"
COLOR_WIP = "#e0af68"


def _heatmap_color(additions: int, deletions: int) -> str:
    """Compute heatmap color based on add/delete ratio."""
    total = additions + deletions
    if total == 0:
        return COLOR_DIM
    ratio = additions / total  # 1.0 = pure adds, 0.0 = pure deletes
    if ratio > 0.7:
        return COLOR_GREEN
    elif ratio < 0.3:
        return COLOR_RED
    else:
        return COLOR_AMBER


def _tick_height(total_changes: int, max_height: int = 4) -> int:
    """Compute tick height proportional to changes, capped."""
    if total_changes == 0:
        return 1
    if total_changes >= 100:
        return max_height
    return max(1, min(max_height, total_changes // 25 + 1))


class TimelineWidget(Widget, can_focus=True):
    """Horizontal commit timeline with heatmap ticks.

    Navigation: h/l/arrows move cursor. Diff shows current vs previous commit.
    Pinning: press x to pin start, move, press x to pin end (diff shows range).
    Press x again or Esc to clear pins and return to step-through mode.
    """

    BINDINGS = [
        ("h", "move_cursor(-1)", "Left"),
        ("l", "move_cursor(1)", "Right"),
        ("left", "move_cursor(-1)", "Left"),
        ("right", "move_cursor(1)", "Right"),
        ("0", "jump_first", "First"),
        ("$", "jump_last", "Last"),
        ("x", "pin", "Pin"),
        ("X", "snap_pin", "Snap nearest pin"),
        ("escape", "clear_pins", "Clear pins"),
    ]

    cursor: reactive[int] = reactive(0)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.commits: list[CommitInfo] = []
        self._all_commits: list[CommitInfo] = []
        self.time_filter: str = ""  # e.g. "3m", "2025-06-01", or "" for all
        self.pin_start: int | None = None
        self.pin_end: int | None = None

    @property
    def has_pins(self) -> bool:
        return self.pin_start is not None

    @property
    def pins_locked(self) -> bool:
        return self.pin_start is not None and self.pin_end is not None

    def set_commits(self, commits: list[CommitInfo]) -> None:
        """Load commits and reset pins."""
        self._all_commits = commits
        self.time_filter = ""
        self.commits = commits
        self.pin_start = None
        self.pin_end = None
        if commits:
            self.cursor = len(commits) - 1
        else:
            self.cursor = 0
        self._notify()
        self.refresh()

    def apply_time_filter(self, filter_str: str) -> None:
        """Filter commits by time. Supports: '1w', '1m', '3m', '6m', '1y', 'YYYY-MM-DD', or '' for all."""
        from datetime import datetime, timedelta, timezone

        self.time_filter = filter_str
        self.pin_start = None
        self.pin_end = None

        if not filter_str:
            self.commits = list(self._all_commits)
        else:
            now = datetime.now(tz=timezone.utc)
            cutoff = None

            # Parse relative time
            if filter_str.endswith("w"):
                try:
                    weeks = int(filter_str[:-1])
                    cutoff = now - timedelta(weeks=weeks)
                except ValueError:
                    pass
            elif filter_str.endswith("m"):
                try:
                    months = int(filter_str[:-1])
                    cutoff = now - timedelta(days=months * 30)
                except ValueError:
                    pass
            elif filter_str.endswith("y"):
                try:
                    years = int(filter_str[:-1])
                    cutoff = now - timedelta(days=years * 365)
                except ValueError:
                    pass
            else:
                # Try parsing as date
                try:
                    cutoff = datetime.strptime(filter_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

            if cutoff:
                self.commits = [c for c in self._all_commits if c.date >= cutoff]
            else:
                self.commits = list(self._all_commits)

        if self.commits:
            self.cursor = len(self.commits) - 1
        else:
            self.cursor = 0
        self._notify()
        self.refresh()

    @property
    def left_cursor(self) -> int:
        """Left index for diff computation."""
        if self.pins_locked:
            return min(self.pin_start, self.pin_end)
        elif self.pin_start is not None:
            # Live preview: range from pin to cursor
            return min(self.pin_start, self.cursor)
        else:
            # Step mode: current vs previous
            return max(0, self.cursor - 1)

    @property
    def right_cursor(self) -> int:
        """Right index for diff computation."""
        if self.pins_locked:
            return max(self.pin_start, self.pin_end)
        elif self.pin_start is not None:
            return max(self.pin_start, self.cursor)
        else:
            return self.cursor

    def render(self) -> Text:
        if not self.commits:
            return Text("No commits", style=COLOR_DIM)

        width = self.size.width - 2
        height = max(self.size.height - 1, 3)
        max_tick_h = min(4, height - 1)

        text = Text()

        # Top label row
        commit = self.commits[self.cursor]
        if self.pins_locked:
            s = self.commits[self.pin_start].short_hash
            e = self.commits[self.pin_end].short_hash
            label = f" ✕ {s} → {e}  (x or Esc to clear)  ▸ {commit.short_hash}  ({self.cursor + 1}/{len(self.commits)})"
        elif self.pin_start is not None:
            s = self.commits[self.pin_start].short_hash
            label = f" ✕ {s} → ...  (x to pin end)  ▸ {commit.short_hash}  ({self.cursor + 1}/{len(self.commits)})"
        else:
            label = f" ▸ {commit.short_hash}  ({self.cursor + 1}/{len(self.commits)})  x to pin"
        text.append(label, style=COLOR_DIM)
        text.append("\n")

        # Determine range for highlighting
        has_range = self.pin_start is not None
        range_lo = range_hi = 0
        if has_range:
            if self.pin_end is not None:
                range_lo = min(self.pin_start, self.pin_end)
                range_hi = max(self.pin_start, self.pin_end)
            else:
                range_lo = min(self.pin_start, self.cursor)
                range_hi = max(self.pin_start, self.cursor)

        # Build tick display rows
        n = len(self.commits)
        max_ticks = min(n, 50)  # cap visible ticks for consistent spacing

        if max_ticks <= 0:
            base_gap = 0
            extra = 0
            view_start = 0
            view_end = 0
        elif n <= max_ticks:
            # All commits fit — distribute evenly across width
            gap_count = n - 1
            if gap_count > 0:
                base_gap = (width - n) // gap_count
                extra = (width - n) - base_gap * gap_count
            else:
                base_gap = 0
                extra = 0
            view_start = 0
            view_end = n
        else:
            # More commits than max_ticks — scrolling window centered on cursor
            # Reserve 2 chars for overflow arrows ◀ ▶
            usable = width - 2
            visible = min(max_ticks, usable)
            # Total chars = visible ticks + (visible-1) gaps = usable
            # So (visible-1) gaps = usable - visible
            gap_count = visible - 1
            if gap_count > 0:
                base_gap = (usable - visible) // gap_count
                extra = (usable - visible) - base_gap * gap_count
            else:
                base_gap = 0
                extra = 0
            half = visible // 2
            view_start = max(0, self.cursor - half)
            view_end = min(n, view_start + visible)
            if view_end == n:
                view_start = max(0, n - visible)
            if view_start == 0:
                view_end = min(n, visible)

        # Scroll indicators
        has_left_overflow = view_start > 0
        has_right_overflow = view_end < n
        view_count = view_end - view_start

        def _gap_for(vi: int) -> int:
            """Get gap width after tick at visual index vi. Distributes extra chars evenly."""
            if vi >= view_count - 1:
                return 0
            # Bresenham-style even distribution of extra gaps across all ticks
            if extra > 0 and view_count > 1:
                # Tick vi gets an extra char if floor((vi+1)*extra/slots) > floor(vi*extra/slots)
                slots = view_count - 1
                has_extra = ((vi + 1) * extra // slots) > (vi * extra // slots)
                return base_gap + (1 if has_extra else 0)
            return base_gap

        # Helper to render a row across the visible window
        def _render_row(char_fn, show_arrows=False):
            """char_fn(i) -> (char, style) for commit index i."""
            if has_left_overflow:
                if show_arrows:
                    text.append("◀", style=COLOR_DIM)
                else:
                    text.append(" ")
            for vi, i in enumerate(range(view_start, view_end)):
                char, style = char_fn(i)
                text.append(char, style=style)
                gap = _gap_for(vi)
                if gap > 0:
                    in_range = has_range and range_lo <= i <= range_hi
                    gap_char = "─" if in_range and i < range_hi else " "
                    gap_style = f"{COLOR_DIM} on {COLOR_RANGE}" if in_range and i < range_hi else ""
                    text.append(gap_char * gap, style=gap_style)
            if has_right_overflow:
                if show_arrows:
                    text.append("▶", style=COLOR_DIM)
                else:
                    text.append(" ")
            text.append("\n")

        # WIP label row above the ticks
        has_wip = any(c.is_wip for c in self.commits[view_start:view_end])
        if has_wip:
            def _wip_row(i):
                if self.commits[i].is_wip:
                    return ("W", f"bold {COLOR_WIP}")
                return (" ", "")
            _render_row(_wip_row)

        # Tick rows — show arrow on the middle row only
        mid_row = (max_tick_h + 1) // 2
        for row in range(max_tick_h, 0, -1):
            def _tick_row(i, _row=row):
                commit = self.commits[i]
                h = _tick_height(commit.total_changes, max_tick_h)
                color = _heatmap_color(commit.additions, commit.deletions)
                is_wip = commit.is_wip
                in_range = has_range and range_lo <= i <= range_hi

                if h >= _row:
                    char = "░" if is_wip else "█"
                    if i == self.cursor:
                        style = f"bold {COLOR_WIP}" if is_wip else f"bold {COLOR_CURSOR}"
                    elif has_range and i == self.pin_start:
                        style = f"bold {COLOR_PIN_START}"
                    elif has_range and self.pin_end is not None and i == self.pin_end:
                        style = f"bold {COLOR_PIN_END}"
                    else:
                        style = f"{COLOR_WIP}" if is_wip else color
                        if in_range:
                            style = f"{style} on {COLOR_RANGE}"
                    return (char, style)
                elif in_range:
                    return ("·", f"{COLOR_DIM} on {COLOR_RANGE}")
                return (" ", "")
            _render_row(_tick_row, show_arrows=(row == mid_row))

        # Indicator row
        def _indicator_row(i):
            is_wip = self.commits[i].is_wip
            if i == self.cursor:
                return ("●", f"bold {COLOR_WIP}" if is_wip else f"bold {COLOR_CURSOR}")
            elif has_range and i == self.pin_start:
                return ("●", f"bold {COLOR_PIN_START}")
            elif has_range and self.pin_end is not None and i == self.pin_end:
                return ("●", f"bold {COLOR_PIN_END}")
            elif is_wip:
                return ("◆", f"bold {COLOR_WIP}")
            return (" ", COLOR_DIM)
        _render_row(_indicator_row)

        # Label row — with "◀more" / "more▶" text at edges
        if has_left_overflow:
            text.append("◀", style=f"bold {COLOR_DIM}")
        elif has_right_overflow:
            text.append(" ")
        for vi, i in enumerate(range(view_start, view_end)):
            is_wip = self.commits[i].is_wip
            if i == self.cursor:
                char = "▸"
                style = f"bold {COLOR_WIP}" if is_wip else f"bold {COLOR_CURSOR}"
            elif has_range and i == self.pin_start:
                char = "✕"
                style = f"bold {COLOR_PIN_START}"
            elif has_range and self.pin_end is not None and i == self.pin_end:
                char = "✕"
                style = f"bold {COLOR_PIN_END}"
            else:
                char = "·"
                style = COLOR_DIM
            text.append(char, style=style)
            gap = _gap_for(vi)
            if gap > 0:
                text.append(" " * gap)
        if has_right_overflow:
            text.append("▶", style=f"bold {COLOR_DIM}")
        elif has_left_overflow:
            text.append(" ")
        text.append("\n")

        return text

    def action_move_cursor(self, delta: int) -> None:
        if not self.commits:
            return
        new = max(0, min(len(self.commits) - 1, self.cursor + delta))
        if new != self.cursor:
            self.cursor = new
            self._notify()

    def action_jump_first(self) -> None:
        if self.commits and self.cursor != 0:
            self.cursor = 0
            self._notify()

    def action_jump_last(self) -> None:
        if self.commits:
            last = len(self.commits) - 1
            if self.cursor != last:
                self.cursor = last
                self._notify()

    def action_pin(self) -> None:
        """Pin commits with x. First x = start, second x = end, third x = clear."""
        if not self.commits:
            return

        if self.pin_start is None:
            # First pin: mark start
            self.pin_start = self.cursor
            self.refresh()
        elif self.pin_end is None:
            # Second pin: mark end, lock the range
            self.pin_end = self.cursor
            self._notify()
        else:
            # Third pin: clear everything, back to step mode
            self._clear_pins()

    def action_snap_pin(self) -> None:
        """Snap the nearest pin to the current cursor position."""
        if not self.commits or not self.has_pins:
            return

        if self.pin_end is None:
            # Only start pin exists — snap it
            self.pin_start = self.cursor
        else:
            # Both pins exist — snap whichever is closer
            dist_start = abs(self.cursor - self.pin_start)
            dist_end = abs(self.cursor - self.pin_end)
            if dist_start <= dist_end:
                self.pin_start = self.cursor
            else:
                self.pin_end = self.cursor
        self._notify()

    def action_clear_pins(self) -> None:
        """Clear pins and return to step-through mode."""
        if self.has_pins:
            self._clear_pins()

    def _clear_pins(self) -> None:
        self.pin_start = None
        self.pin_end = None
        self._notify()

    def _notify(self) -> None:
        self.refresh()
        self.post_message(CursorMoved(self.left_cursor, self.right_cursor))

    def jump_to_commit_index(self, idx: int) -> None:
        """Jump cursor to a specific commit index."""
        if not self.commits:
            return
        idx = max(0, min(len(self.commits) - 1, idx))
        self.cursor = idx
        self._notify()
