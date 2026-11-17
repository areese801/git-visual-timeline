"""
Shared pieces for the Evolution views: the period message and a base widget.
"""

from __future__ import annotations

from datetime import date, tzinfo

from rich.text import Text
from textual.message import Message
from textual.widget import Widget

from gvt.git.repo import CommitInfo, TagInfo

COLOR_DIM = "#565f89"
COLOR_TEXT = "#c0caf5"
COLOR_GREEN = "#9ece6a"
COLOR_RED = "#f7768e"
COLOR_AMBER = "#e0af68"
COLOR_PURPLE = "#bb9af7"

# Below this size the views show a hint instead of a chart
MIN_WIDTH = 40
MIN_HEIGHT = 10


class PeriodChosen(Message):
    """
    Posted when the user presses Enter on a day or period.
    """

    def __init__(self, start: date, end: date, label: str) -> None:
        self.start = start
        self.end = end  # exclusive
        self.label = label
        super().__init__()


def format_count(n: int) -> str:
    """
    Thousands-separated integer, e.g. 1,204.
    """
    return f"{n:,}"


def plural(n: int, word: str) -> str:
    """
    '1 commit' / '6 commits'.
    """
    return f"{format_count(n)} {word}{'' if n == 1 else 's'}"


class EvolutionView(Widget, can_focus=True):
    """
    Base for views that render commits over time.

    Holds the scope's commits and tags, a message shown instead of the chart
    (loading, empty, errors), and the time zone used for day bucketing
    (None = local; tests pass UTC).
    """

    # Rows needed to draw the chart and its status line
    min_height = MIN_HEIGHT

    def __init__(self, tz: tzinfo | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.tz = tz
        self.commits: list[CommitInfo] = []
        self.tags: list[TagInfo] = []
        # Lines in scope before the oldest commit shown (non-zero when filtered)
        self.base_size = 0
        self.message: str = "Loading history…"

    def set_data(self, commits: list[CommitInfo], tags: list[TagInfo], base_size: int = 0) -> None:
        """
        Show these commits (any order) and tags; clears any message.

        :param base_size: Net lines added by commits older than these (the
            scope's size where the shown history starts).
        """
        self.commits = commits
        self.tags = tags
        self.base_size = base_size
        self.message = ""
        self.on_data_changed()
        self.refresh()

    def set_message(self, message: str) -> None:
        """
        Replace the chart with a centered message.
        """
        self.message = message
        self.refresh()

    def on_data_changed(self) -> None:
        """
        Hook for subclasses to recompute state after set_data().
        """

    def status_text(self) -> Text:
        """
        One-line summary of the item under the cursor.
        """
        return Text()

    def _render_message(self, message: str) -> Text:
        height = max(self.size.height, 1)
        text = Text("\n" * (height // 2))
        text.append(message.center(max(self.size.width, len(message))), style=COLOR_DIM)
        return text

    def _too_small(self) -> bool:
        return self.size.width < MIN_WIDTH or self.size.height < self.min_height

    def _status_line(self, base: Text, tag_names: list[str]) -> Text:
        """
        Status text plus tag names, in the shared style.
        """
        if tag_names:
            base.append("  ·  ", style=COLOR_DIM)
            base.append("▲ " + ", ".join(tag_names), style=COLOR_PURPLE)
        return base
