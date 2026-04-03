"""Diff view widget for gvt."""

from __future__ import annotations

import re as re_module

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
MODE_SIDE_BY_SIDE = "side_by_side"


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
        self.side_by_side: bool = False
        self._full_file_content: str = ""
        self._full_file_diff_lines: set[int] = set()
        self._full_file_add_lines: set[int] = set()
        self._full_file_del_lines: set[int] = set()
        self._flash_lines: set[int] = set()
        self._flash_timer = None
        self.blame_enabled: bool = False
        self._blame_data: list[tuple[str, str, str]] = []  # (hash, author, date) per line
        # Search state
        self._search_mode: bool = False
        self._search_pattern: re_module.Pattern | None = None
        self._search_query: str = ""
        self._search_match_lines: list[int] = []
        self._search_match_idx: int = -1
        self._search_highlight_lines: set[int] = set()

    def set_diff(self, diff: str) -> None:
        self.diff_text = diff

    def set_full_file(self, content: str, diff: str) -> None:
        """Set full file content and the diff to highlight changed lines."""
        self._full_file_content = content
        self._parse_diff_line_numbers(diff)
        if self.view_mode == MODE_FULL:
            self._render_full_file()

    def watch_diff_text(self, value: str) -> None:
        if self.side_by_side and self.view_mode == MODE_DIFF:
            self._render_side_by_side(value)
        elif self.view_mode == MODE_DIFF:
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
                match = re_module.search(r"\+(\d+)", raw_line)
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
                match = re_module.search(r"\+(\d+)", raw_line)
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

    def _render_side_by_side(self, diff: str) -> None:
        """Parse unified diff into side-by-side columns."""
        self._lines = []
        self._hunk_positions = []

        if not diff:
            self._lines.append(Text("No diff to display", style=COLOR_DIM))
            return

        # Parse diff into pairs of (old_line, new_line)
        pairs: list[tuple[str | None, str | None, str]] = []  # (left, right, type)
        old_buf: list[str] = []
        new_buf: list[str] = []

        def flush_buffers():
            """Pair up old/new deletions and additions."""
            max_len = max(len(old_buf), len(new_buf))
            for i in range(max_len):
                left = old_buf[i] if i < len(old_buf) else None
                right = new_buf[i] if i < len(new_buf) else None
                if left and right:
                    pairs.append((left, right, "change"))
                elif left:
                    pairs.append((left, None, "del"))
                else:
                    pairs.append((None, right, "add"))
            old_buf.clear()
            new_buf.clear()

        for raw_line in diff.split("\n"):
            if raw_line.startswith("@@"):
                flush_buffers()
                pairs.append((raw_line, raw_line, "hunk"))
            elif raw_line.startswith("-"):
                old_buf.append(raw_line[1:])
            elif raw_line.startswith("+"):
                new_buf.append(raw_line[1:])
            else:
                flush_buffers()
                # Context line (strip leading space)
                content = raw_line[1:] if raw_line.startswith(" ") else raw_line
                pairs.append((content, content, "context"))

        flush_buffers()

        # Render pairs
        col_width = max(20, (self.size.width - 3) // 2)  # 3 for " │ "
        divider = " │ "

        # Header
        header = Text()
        header.append("  SIDE-BY-SIDE DIFF  ", style=f"bold {COLOR_HUNK}")
        header.append("[d] back to inline  ", style=COLOR_DIM)
        header.append("[+/-] context", style=COLOR_DIM)
        self._lines.append(header)

        for left, right, ptype in pairs:
            line = Text()

            if ptype == "hunk":
                self._hunk_positions.append(len(self._lines))
                # Show hunk header across full width
                line.append(left[:col_width].ljust(col_width), style=f"bold {COLOR_HUNK}")
                line.append(divider, style=COLOR_DIM)
                line.append(right[:col_width].ljust(col_width), style=f"bold {COLOR_HUNK}")
            elif ptype == "context":
                line.append((left or "")[:col_width].ljust(col_width), style=COLOR_TEXT)
                line.append(divider, style=COLOR_DIM)
                line.append((right or "")[:col_width].ljust(col_width), style=COLOR_TEXT)
            elif ptype == "del":
                line.append((left or "")[:col_width].ljust(col_width), style=f"{COLOR_DEL_FG} on {COLOR_DEL_BG}")
                line.append(divider, style=COLOR_DIM)
                line.append(" " * col_width, style="")
            elif ptype == "add":
                line.append(" " * col_width, style="")
                line.append(divider, style=COLOR_DIM)
                line.append((right or "")[:col_width].ljust(col_width), style=f"{COLOR_ADD_FG} on {COLOR_ADD_BG}")
            elif ptype == "change":
                line.append((left or "")[:col_width].ljust(col_width), style=f"{COLOR_DEL_FG} on {COLOR_DEL_BG}")
                line.append(divider, style=COLOR_DIM)
                line.append((right or "")[:col_width].ljust(col_width), style=f"{COLOR_ADD_FG} on {COLOR_ADD_BG}")

            self._lines.append(line)

        self.virtual_size = self.size.with_height(max(len(self._lines), 1))
        self.refresh()

    def action_toggle_side_by_side(self) -> None:
        """Toggle between inline and side-by-side diff mode."""
        self.side_by_side = not self.side_by_side
        if self.view_mode == MODE_FULL:
            self.view_mode = MODE_DIFF
        if self.side_by_side:
            self._render_side_by_side(self.diff_text)
        else:
            self._parse_diff(self.diff_text)
            self.virtual_size = self.size.with_height(max(len(self._lines), 1))
        self.scroll_home(animate=False)
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

        # Search input overlay at the bottom of the visible area
        if self._search_mode and y == self.size.height - 1:
            search_text = f"/{self._search_query}"
            match_info = ""
            if self._search_match_lines:
                match_info = f"  [{self._search_match_idx + 1}/{len(self._search_match_lines)}]"
            prompt = search_text + match_info
            bar_style = Style(bgcolor="#24283b", color="#c0caf5")
            segments = [Segment(prompt.ljust(self.size.width), bar_style)]
            return Strip(segments)

        scroll_y = int(self.scroll_offset.y)
        line_idx = y + scroll_y

        if line_idx < len(self._lines):
            text = self._lines[line_idx]
            segments = list(text.render(self.app.console))

            # Apply search highlight
            if line_idx in self._search_highlight_lines:
                hl_style = Style(bgcolor="#2a3a5a")
                segments = [
                    Segment(s.text, s.style + hl_style if s.style else hl_style, s.control)
                    for s in segments
                ]
                # Extra highlight for current match
                if self._search_match_lines and self._search_match_idx >= 0:
                    if line_idx == self._search_match_lines[self._search_match_idx]:
                        cur_style = Style(bgcolor="#3d4f7a")
                        segments = [
                            Segment(s.text, s.style + cur_style if s.style else cur_style, s.control)
                            for s in segments
                        ]

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
        # If search highlights are active, n goes to next match
        if self._search_match_lines and not self._search_mode:
            self._search_next()
            return
        if not self._hunk_positions:
            return
        current_y = int(self.scroll_offset.y)
        for pos in self._hunk_positions:
            if pos > current_y:
                self.scroll_to(y=pos, animate=False)
                self._flash_hunk(pos)
                return

    def action_prev_hunk(self) -> None:
        # If search highlights are active, N goes to prev match
        if self._search_match_lines and not self._search_mode:
            self._search_prev()
            return
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

    # --- Diff search ---

    def action_start_search(self) -> None:
        """Enter search mode — show input overlay at bottom of diff."""
        self._search_mode = True
        self._search_query = ""
        self._search_pattern = None
        self._search_match_lines = []
        self._search_match_idx = -1
        self._search_highlight_lines = set()
        self.refresh()

    def _apply_search(self, query: str) -> None:
        """Compile regex and find matching lines."""
        self._search_query = query
        self._search_highlight_lines = set()
        self._search_match_lines = []
        self._search_match_idx = -1

        if not query:
            self._search_pattern = None
            self.refresh()
            return

        try:
            self._search_pattern = re_module.compile(query, re_module.IGNORECASE)
        except re_module.error:
            self._search_pattern = None
            self.refresh()
            return

        for idx, line in enumerate(self._lines):
            if self._search_pattern.search(line.plain):
                self._search_match_lines.append(idx)
                self._search_highlight_lines.add(idx)

        # Jump to first match
        if self._search_match_lines:
            self._search_match_idx = 0
            self.scroll_to(y=self._search_match_lines[0], animate=False)

        self.refresh()

    def _search_next(self) -> None:
        """Jump to next search match."""
        if not self._search_match_lines:
            return
        self._search_match_idx = (self._search_match_idx + 1) % len(self._search_match_lines)
        self.scroll_to(y=self._search_match_lines[self._search_match_idx], animate=False)
        self.refresh()

    def _search_prev(self) -> None:
        """Jump to previous search match."""
        if not self._search_match_lines:
            return
        self._search_match_idx = (self._search_match_idx - 1) % len(self._search_match_lines)
        self.scroll_to(y=self._search_match_lines[self._search_match_idx], animate=False)
        self.refresh()

    def _exit_search(self) -> None:
        """Exit search mode and clear highlights."""
        self._search_mode = False
        self._search_pattern = None
        self._search_query = ""
        self._search_match_lines = []
        self._search_match_idx = -1
        self._search_highlight_lines = set()
        self.refresh()

    def on_key(self, event) -> None:
        """Handle search mode key events."""
        if not self._search_mode:
            if event.key == "slash":
                self.action_start_search()
                event.prevent_default()
                event.stop()
            elif event.key == "escape" and self._search_highlight_lines:
                self._exit_search()
                event.prevent_default()
                event.stop()
            return

        # In search mode, capture all keys
        event.prevent_default()
        event.stop()

        if event.key == "escape":
            self._exit_search()
        elif event.key == "enter":
            # Confirm search, stay in highlight mode for n/N navigation
            self._search_mode = False
            self.refresh()
        elif event.key == "backspace":
            self._apply_search(self._search_query[:-1])
        elif event.character and len(event.character) == 1 and event.character.isprintable():
            self._apply_search(self._search_query + event.character)

    def _handle_search_navigation(self, event) -> bool:
        """Handle n/N for search navigation when not in search input mode. Returns True if handled."""
        if not self._search_match_lines or self._search_mode:
            return False
        if event.key == "n":
            self._search_next()
            return True
        elif event.key == "N":
            self._search_prev()
            return True
        elif event.key == "escape":
            self._exit_search()
            return True
        return False

    def set_message(self, msg: str) -> None:
        """Display a simple message instead of a diff."""
        self._lines = [Text(msg, style=COLOR_DIM)]
        self._hunk_positions = []
        self.virtual_size = self.size.with_height(1)
        self.refresh()
