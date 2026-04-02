"""Diff view widget for gvt."""

from __future__ import annotations

from rich.text import Text
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView

COLOR_ADD_BG = "#1f2d1f"
COLOR_DEL_BG = "#2d1f1f"
COLOR_ADD_FG = "#9ece6a"
COLOR_DEL_FG = "#f7768e"
COLOR_HUNK = "#7aa2f7"
COLOR_LINE_NO = "#565f89"
COLOR_TEXT = "#c0caf5"
COLOR_DIM = "#565f89"
COLOR_FLASH = "#3d3d6b"

MODE_DIFF = "diff"
MODE_FULL = "full"


class DiffContextChanged(Message):
    """Posted when context lines or view mode changes, requesting a diff reload."""

    def __init__(self, context_lines: int, full_file: bool) -> None:
        self.context_lines = context_lines
        self.full_file = full_file
        super().__init__()


class DiffViewWidget(ScrollView, can_focus=True):
    """Syntax-highlighted diff viewer with line numbers."""

    BINDINGS = [
        ("j", "scroll_down", "Down"),
        ("k", "scroll_up", "Up"),
        ("down", "scroll_down", "Down"),
        ("up", "scroll_up", "Up"),
        ("g", "scroll_home", "Top"),
        ("G", "scroll_end", "Bottom"),
        ("n", "next_hunk", "Next hunk"),
        ("p", "prev_hunk", "Prev hunk"),
        ("N", "prev_hunk", "Prev hunk"),
        ("P", "next_hunk", "Next hunk"),
        ("plus", "more_context", "+context"),
        ("minus", "less_context", "-context"),
        ("m", "more_context", "+context"),
        ("l", "less_context", "-context"),
        ("M", "less_context", "-context"),
        ("L", "more_context", "+context"),
        ("w", "toggle_full_file", "Whole file"),
    ]

    diff_text: reactive[str] = reactive("")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._lines: list[Text] = []
        self._hunk_positions: list[int] = []
        self.context_lines: int = 3
        self.view_mode: str = MODE_DIFF
        self._full_file_content: str = ""
        self._full_file_diff_lines: set[int] = set()
        self._full_file_add_lines: set[int] = set()
        self._full_file_del_lines: set[int] = set()
        self._flash_lines: set[int] = set()
        self._flash_timer = None
        self.blame_enabled: bool = False
        self._blame_data: list[tuple[str, str, str]] = []  # (hash, author, date) per line

    def set_diff(self, diff: str) -> None:
        self.diff_text = diff

    def set_full_file(self, content: str, diff: str) -> None:
        """Set full file content and the diff to highlight changed lines."""
        self._full_file_content = content
        self._parse_diff_line_numbers(diff)
        if self.view_mode == MODE_FULL:
            self._render_full_file()

    def watch_diff_text(self, value: str) -> None:
        if self.view_mode == MODE_DIFF:
            self._parse_diff(value)
        else:
            self._parse_diff_line_numbers(value)
            self._render_full_file()
        self.virtual_size = self.size.with_height(max(len(self._lines), 1))
        self.scroll_home(animate=False)
        self.refresh()

    def _parse_diff(self, diff: str) -> None:
        """Parse diff into styled Rich Text lines."""
        self._lines = []
        self._hunk_positions = []
        self._diff_line_to_file_line: dict[int, int] = {}

        if not diff:
            self._lines.append(Text("No diff to display", style=COLOR_DIM))
            return

        lines = diff.split("\n")
        line_no = 0
        new_file_line = 0  # tracks position in the new (right) file

        for raw_line in lines:
            line_no += 1
            line = Text()

            gutter = f"{line_no:>4} "
            line.append(gutter, style=COLOR_LINE_NO)

            if raw_line.startswith("@@"):
                self._hunk_positions.append(len(self._lines))
                line.append(raw_line, style=f"bold {COLOR_HUNK}")
                # Parse new file line number from @@ -a,b +c,d @@
                import re
                match = re.search(r"\+(\d+)", raw_line)
                if match:
                    new_file_line = int(match.group(1)) - 1
            elif raw_line.startswith("+"):
                new_file_line += 1
                self._diff_line_to_file_line[len(self._lines)] = new_file_line - 1
                line.append(raw_line, style=f"{COLOR_ADD_FG} on {COLOR_ADD_BG}")
            elif raw_line.startswith("-"):
                # Deletions don't advance new file line
                line.append(raw_line, style=f"{COLOR_DEL_FG} on {COLOR_DEL_BG}")
            else:
                new_file_line += 1
                self._diff_line_to_file_line[len(self._lines)] = new_file_line - 1
                line.append(raw_line, style=COLOR_TEXT)

            self._lines.append(line)

        # Add context info to first line
        mode_info = Text()
        mode_info.append(f"  [context: {self.context_lines}]  ", style=COLOR_DIM)
        mode_info.append("[w] whole file  ", style=COLOR_DIM)
        mode_info.append("[+/-] context", style=COLOR_DIM)
        if self._lines:
            self._lines[0].append_text(mode_info)

    def _parse_diff_line_numbers(self, diff: str) -> None:
        """Extract which lines in the new file were added/changed."""
        self._full_file_add_lines = set()
        self._full_file_del_lines = set()
        if not diff:
            return

        new_line = 0
        for raw_line in diff.split("\n"):
            if raw_line.startswith("@@"):
                # Parse @@ -a,b +c,d @@ to get new file line number
                import re
                match = re.search(r"\+(\d+)", raw_line)
                if match:
                    new_line = int(match.group(1)) - 1
            elif raw_line.startswith("+"):
                new_line += 1
                self._full_file_add_lines.add(new_line)
            elif raw_line.startswith("-"):
                # Deletions don't advance the new file line counter
                # but we track the position for context
                self._full_file_del_lines.add(new_line + 1)
            else:
                new_line += 1

    def _render_full_file(self) -> None:
        """Render the full file with changed lines highlighted."""
        self._lines = []
        self._hunk_positions = []

        if not self._full_file_content:
            self._lines.append(Text("No file content available", style=COLOR_DIM))
            return

        # Header
        header = Text()
        header.append("  WHOLE FILE VIEW  ", style=f"bold {COLOR_HUNK}")
        header.append("[w] back to diff  ", style=COLOR_DIM)
        header.append("[+/-] context", style=COLOR_DIM)
        self._lines.append(header)

        file_lines = self._full_file_content.split("\n")
        for i, file_line in enumerate(file_lines, 1):
            line = Text()
            gutter = f"{i:>4} "

            if i in self._full_file_add_lines:
                line.append(gutter, style=COLOR_ADD_FG)
                line.append(file_line, style=f"{COLOR_ADD_FG} on {COLOR_ADD_BG}")
                self._hunk_positions.append(len(self._lines))
            elif i in self._full_file_del_lines:
                line.append(gutter, style=COLOR_LINE_NO)
                line.append(file_line, style=COLOR_TEXT)
            else:
                line.append(gutter, style=COLOR_LINE_NO)
                line.append(file_line, style=COLOR_TEXT)

            self._lines.append(line)

        self.virtual_size = self.size.with_height(max(len(self._lines), 1))
        self.refresh()

    def set_blame(self, blame_data: list[tuple[str, str, str]]) -> None:
        """Set blame data (hash, author, date) per line of the newer file."""
        self._blame_data = blame_data
        if self.blame_enabled:
            self.refresh()

    def action_toggle_blame(self) -> None:
        """Toggle inline blame annotations."""
        self.blame_enabled = not self.blame_enabled
        self.refresh()

    def _get_blame_for_display_line(self, line_idx: int) -> str | None:
        """Get blame annotation for a display line, if applicable."""
        if not self.blame_enabled or not self._blame_data:
            return None

        # In full-file mode, line_idx maps directly (offset by 1 for header)
        if self.view_mode == MODE_FULL and line_idx > 0:
            file_line = line_idx - 1  # subtract header
            if 0 <= file_line < len(self._blame_data):
                h, author, date = self._blame_data[file_line]
                # Truncate author to 12 chars
                author_short = author[:12].ljust(12)
                return f"{h} {author_short} {date}"
            return None

        # In diff mode, blame applies to context and added lines
        # We need to map display lines back to file lines
        if self.view_mode == MODE_DIFF and line_idx < len(self._lines):
            text_plain = self._lines[line_idx].plain
            # Strip the gutter (line number)
            content = text_plain.lstrip()
            if content.startswith("@@") or content.startswith("-"):
                return None
            # For context and + lines, use the new-file line tracking
            if hasattr(self, '_diff_line_to_file_line') and line_idx in self._diff_line_to_file_line:
                file_line = self._diff_line_to_file_line[line_idx]
                if 0 <= file_line < len(self._blame_data):
                    h, author, date = self._blame_data[file_line]
                    author_short = author[:12].ljust(12)
                    return f"{h} {author_short} {date}"
        return None

    def render_line(self, y: int) -> "Strip":
        from textual.strip import Strip
        from rich.style import Style
        from rich.segment import Segment

        scroll_y = int(self.scroll_offset.y)
        line_idx = y + scroll_y

        if line_idx < len(self._lines):
            text = self._lines[line_idx]
            segments = list(text.render(self.app.console))

            # Apply flash if active
            if line_idx in self._flash_lines:
                flash_style = Style(bgcolor=COLOR_FLASH)
                segments = [
                    Segment(s.text, s.style + flash_style if s.style else flash_style, s.control)
                    for s in segments
                ]

            # Compute content width
            content_width = sum(len(s.text) for s in segments)

            # Add blame annotation right-aligned
            blame_text = self._get_blame_for_display_line(line_idx)
            if blame_text:
                blame_style = Style(color=COLOR_DIM)
                blame_width = len(blame_text) + 2  # 2 for padding
                gap = max(1, self.size.width - content_width - blame_width)
                segments.append(Segment(" " * gap, None))
                segments.append(Segment(blame_text, blame_style))
            elif line_idx in self._flash_lines:
                # Pad flash to full width
                flash_style = Style(bgcolor=COLOR_FLASH)
                if content_width < self.size.width:
                    segments.append(Segment(" " * (self.size.width - content_width), flash_style))

            return Strip(segments)
        from rich.style import Style
        from rich.segment import Segment
        bg = Style(bgcolor="#1a1b26")
        return Strip([Segment(" " * self.size.width, bg)])

    def _flash_hunk(self, hunk_start: int) -> None:
        """Briefly highlight the hunk starting at the given line index."""
        # Find the end of this hunk (next hunk position or end of lines)
        hunk_end = len(self._lines)
        for pos in self._hunk_positions:
            if pos > hunk_start:
                hunk_end = pos
                break

        self._flash_lines = set(range(hunk_start, hunk_end))
        self.refresh()

        # Clear flash after 400ms
        if self._flash_timer is not None:
            self._flash_timer.stop()
        self._flash_timer = self.set_timer(0.4, self._clear_flash)

    def _clear_flash(self) -> None:
        self._flash_lines = set()
        self._flash_timer = None
        self.refresh()

    def action_next_hunk(self) -> None:
        if not self._hunk_positions:
            return
        current_y = int(self.scroll_offset.y)
        for pos in self._hunk_positions:
            if pos > current_y:
                self.scroll_to(y=pos, animate=False)
                self._flash_hunk(pos)
                return

    def action_prev_hunk(self) -> None:
        if not self._hunk_positions:
            return
        current_y = int(self.scroll_offset.y)
        for pos in reversed(self._hunk_positions):
            if pos < current_y:
                self.scroll_to(y=pos, animate=False)
                self._flash_hunk(pos)
                return

    def action_more_context(self) -> None:
        """Increase context lines."""
        self.context_lines = min(999, self.context_lines + 3)
        self.post_message(DiffContextChanged(self.context_lines, self.view_mode == MODE_FULL))

    def action_less_context(self) -> None:
        """Decrease context lines."""
        self.context_lines = max(0, self.context_lines - 3)
        self.post_message(DiffContextChanged(self.context_lines, self.view_mode == MODE_FULL))

    def action_toggle_full_file(self) -> None:
        """Toggle between diff and full-file view."""
        if self.view_mode == MODE_DIFF:
            self.view_mode = MODE_FULL
            self._render_full_file()
        else:
            self.view_mode = MODE_DIFF
            self._parse_diff(self.diff_text)
            self.virtual_size = self.size.with_height(max(len(self._lines), 1))
            self.refresh()

    def set_message(self, msg: str) -> None:
        """Display a simple message instead of a diff."""
        self._lines = [Text(msg, style=COLOR_DIM)]
        self._hunk_positions = []
        self.virtual_size = self.size.with_height(1)
        self.refresh()
