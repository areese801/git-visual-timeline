"""Commit toast — brief floating message shown while scrubbing the timeline."""

from __future__ import annotations

from rich.text import Text
from textual.widget import Widget

COLOR_ACCENT = "#7aa2f7"
COLOR_PURPLE = "#bb9af7"
COLOR_TEXT = "#c0caf5"
COLOR_DIM = "#565f89"
COLOR_GREEN = "#9ece6a"
COLOR_RED = "#f7768e"
COLOR_WIP = "#e0af68"
COLOR_BG = "#24283b"
COLOR_BORDER = "#3b4261"


class CommitToast(Widget):
    """A floating toast showing commit info while scrubbing the timeline."""

    DEFAULT_CSS = """
    CommitToast {
        display: none;
        width: 70%;
        height: auto;
        max-height: 10;
        background: #24283b;
        border: solid #7aa2f7;
        padding: 0 2;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = Text()
        self._dismiss_timer = None

    def show_commit(self, short_hash: str, date_str: str, message: str,
                    author: str, additions: int, deletions: int,
                    is_wip: bool = False) -> None:
        """Show a toast with commit info. Auto-hides after delay."""
        self._text = Text()

        # Line 1: hash, date, author, stats
        if is_wip:
            self._text.append("WIP ", style=f"bold {COLOR_WIP}")
        else:
            self._text.append(f"{short_hash} ", style=f"bold {COLOR_ACCENT}")

        self._text.append(f"{date_str}  ", style=COLOR_DIM)
        self._text.append(f"{author}  ", style=COLOR_PURPLE)
        self._text.append(f"+{additions}", style=COLOR_GREEN)
        self._text.append(f" -{deletions}", style=COLOR_RED)

        # Full message below
        self._text.append("\n")
        self._text.append(message.strip(), style=COLOR_TEXT)

        self.display = True
        if self.parent:
            self.parent.display = True
        self.refresh()

        # Reset dismiss timer
        if self._dismiss_timer is not None:
            self._dismiss_timer.stop()
        self._dismiss_timer = self.set_timer(1.5, self._auto_hide)

    def _auto_hide(self) -> None:
        self._dismiss_timer = None
        self.display = False
        if self.parent:
            self.parent.display = False

    def hide(self) -> None:
        if self._dismiss_timer is not None:
            self._dismiss_timer.stop()
            self._dismiss_timer = None
        self.display = False
        if self.parent:
            self.parent.display = False

    def render(self) -> Text:
        return self._text
