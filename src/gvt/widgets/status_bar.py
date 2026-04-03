"""Status bar widget for gvt — context-sensitive shortcut legend."""

from __future__ import annotations

from rich.text import Text
from textual.widget import Widget
from textual.strip import Strip

COLOR_BAR_BG = "#7aa2f7"
COLOR_BAR_FG = "#1a1b26"

# Shortcuts per focused pane
PANE_SHORTCUTS = {
    "file-tree-widget": [
        ("j/k", "navigate"),
        ("Enter", "select"),
        ("o", "expand"),
        ("f", "search files"),
    ],
    "timeline-widget": [
        ("h/l", "move"),
        ("x", "pin"),
        ("X", "snap"),
        ("0/$", "first/last"),
        ("t", "filter"),
        ("c", "commits"),
    ],
    "commit-bar": [
        ("j/k", "switch row"),
        ("Enter", "full message"),
    ],
    "diff-view": [
        ("j/k", "scroll"),
        ("n/p", "hunks"),
        ("/", "search"),
        ("w", "whole file"),
        ("d", "side-by-side"),
        ("b", "blame"),
        ("+/-", "context"),
    ],
    "changed-files": [
        ("j/k", "navigate"),
        ("Enter", "open file"),
    ],
}

GLOBAL_SHORTCUTS = [
    ("1-5", "panes"),
    ("c", "commits"),
    ("f", "files"),
    ("y", "copy hash"),
    ("e", "editor"),
    ("?", "help"),
    ("q", "quit"),
]


class GVTStatusBar(Widget):
    """Two-line footer: info bar + context-sensitive shortcut legend."""

    DEFAULT_CSS = """
    GVTStatusBar {
        dock: bottom;
        height: 2;
        background: #1a1b26;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.file_path: str = ""
        self.commit_position: str = ""
        self.branch: str = ""
        self.additions: int = 0
        self.deletions: int = 0
        self.diff_mode: str = "inline"
        self.focused_pane: str = ""

    def update_info(
        self,
        file_path: str = "",
        commit_position: str = "",
        branch: str = "",
        additions: int = 0,
        deletions: int = 0,
    ) -> None:
        self.file_path = file_path
        self.commit_position = commit_position
        self.branch = branch
        self.additions = additions
        self.deletions = deletions
        self.refresh()

    def set_focused_pane(self, pane_id: str) -> None:
        self.focused_pane = pane_id
        self.refresh()

    def _render_info_line(self) -> Text:
        """Line 1: file info bar."""
        text = Text()
        text.append(" gvt", style=f"bold on {COLOR_BAR_BG} {COLOR_BAR_FG}")

        if self.file_path:
            text.append(f"  {self.file_path}", style=f"on {COLOR_BAR_BG} {COLOR_BAR_FG}")

        if self.commit_position:
            text.append(f"  [{self.commit_position}]", style=f"on {COLOR_BAR_BG} {COLOR_BAR_FG}")

        if self.branch:
            text.append(f"  ⎇ {self.branch}", style=f"on {COLOR_BAR_BG} {COLOR_BAR_FG}")

        if self.additions or self.deletions:
            text.append(f"  +{self.additions} -{self.deletions}", style=f"on {COLOR_BAR_BG} {COLOR_BAR_FG}")

        text.append(f"  {self.diff_mode}", style=f"on {COLOR_BAR_BG} {COLOR_BAR_FG}")

        return text

    def _render_shortcut_line(self) -> Text:
        """Line 2: context-sensitive shortcut legend."""
        text = Text()

        shortcuts = PANE_SHORTCUTS.get(self.focused_pane, [])
        if shortcuts:
            for key, desc in shortcuts:
                text.append(f" {key} ", style="bold #c0caf5 on #3b4261")
                text.append(f" {desc} ", style="#565f89")
            text.append("  │  ", style="#3b4261")

        for key, desc in GLOBAL_SHORTCUTS:
            text.append(f" {key} ", style="bold #c0caf5 on #3b4261")
            text.append(f" {desc} ", style="#565f89")

        return text

    def render_line(self, y: int) -> Strip:
        from rich.segment import Segment
        from rich.style import Style

        if y == 0:
            text = self._render_info_line()
            segments = list(text.render(self.app.console))
            # Pad to full width with bar bg
            rendered_width = sum(len(s.text) for s in segments)
            if rendered_width < self.size.width:
                pad_style = Style(bgcolor=COLOR_BAR_BG, color=COLOR_BAR_FG)
                segments.append(Segment(" " * (self.size.width - rendered_width), pad_style))
            return Strip(segments)
        elif y == 1:
            text = self._render_shortcut_line()
            segments = list(text.render(self.app.console))
            return Strip(segments)

        return Strip.blank(self.size.width)
