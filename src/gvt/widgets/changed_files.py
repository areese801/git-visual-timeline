"""Changed files panel for gvt — shows files changed in the current commit."""

from __future__ import annotations

from rich.text import Text
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView

COLOR_ACCENT = "#7aa2f7"
COLOR_TEXT = "#c0caf5"
COLOR_DIM = "#565f89"
COLOR_GREEN = "#9ece6a"
COLOR_RED = "#f7768e"
COLOR_SELECTED_BG = "#283457"


class ChangedFileSelected(Message):
    """A file was selected from the changed files panel."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__()


class ChangedFilesWidget(ScrollView, can_focus=True):
    """Compact scrollable list of files changed in the current commit."""

    BINDINGS = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("up", "cursor_up", "Up"),
        ("enter", "select_file", "Select"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.files: list[tuple[str, int, int]] = []
        self.selected_idx: int = 0
        self._lines: list[Text] = []

    def set_files(self, files: list[tuple[str, int, int]]) -> None:
        """Update the file list."""
        self.files = files
        self.selected_idx = 0
        self._build_lines()
        self.virtual_size = self.size.with_height(max(len(self._lines), 1))
        self.scroll_home(animate=False)
        self.refresh()

    def clear(self) -> None:
        self.files = []
        self.selected_idx = 0
        self._lines = [Text("No commit selected", style=COLOR_DIM)]
        self.virtual_size = self.size.with_height(1)
        self.refresh()

    def _build_lines(self) -> None:
        self._lines = []
        if not self.files:
            self._lines.append(Text("No files changed", style=COLOR_DIM))
            return

        for idx, (file_path, adds, dels) in enumerate(self.files):
            line = Text()
            is_selected = idx == self.selected_idx

            if is_selected:
                line.append("▸ ", style=f"bold {COLOR_ACCENT}")
            else:
                line.append("  ")

            line.append(file_path, style=COLOR_TEXT if not is_selected else f"bold {COLOR_TEXT}")
            line.append("  ", style="")
            line.append(f"+{adds}", style=COLOR_GREEN)
            line.append(f" -{dels}", style=COLOR_RED)

            self._lines.append(line)

    def render_line(self, y: int) -> "Strip":
        from textual.strip import Strip
        from rich.style import Style
        from rich.segment import Segment

        scroll_y = int(self.scroll_offset.y)
        line_idx = y + scroll_y

        if line_idx < len(self._lines):
            text = self._lines[line_idx]
            segments = list(text.render(self.app.console))
            if line_idx == self.selected_idx and self.files:
                bg_style = Style(bgcolor=COLOR_SELECTED_BG)
                segments = [
                    Segment(s.text, s.style + bg_style if s.style else bg_style, s.control)
                    for s in segments
                ]
                rendered_width = sum(len(s.text) for s in segments)
                if rendered_width < self.size.width:
                    segments.append(Segment(" " * (self.size.width - rendered_width), bg_style))
            return Strip(segments)
        from rich.style import Style
        from rich.segment import Segment
        bg = Style(bgcolor="#1a1b26")
        return Strip([Segment(" " * self.size.width, bg)])

    def action_cursor_down(self) -> None:
        if self.files and self.selected_idx < len(self.files) - 1:
            self.selected_idx += 1
            self._build_lines()
            # Scroll to keep selection visible
            if self.selected_idx >= int(self.scroll_offset.y) + self.size.height:
                self.scroll_to(y=self.selected_idx - self.size.height + 1, animate=False)
            self.refresh()

    def action_cursor_up(self) -> None:
        if self.files and self.selected_idx > 0:
            self.selected_idx -= 1
            self._build_lines()
            if self.selected_idx < int(self.scroll_offset.y):
                self.scroll_to(y=self.selected_idx, animate=False)
            self.refresh()

    def action_select_file(self) -> None:
        if self.files:
            file_path, _, _ = self.files[self.selected_idx]
            self.post_message(ChangedFileSelected(file_path))
