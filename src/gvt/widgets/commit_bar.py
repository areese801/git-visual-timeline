"""Commit message bar widget for gvt."""

from __future__ import annotations

from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from rich.text import Text

from gvt.git.repo import CommitInfo


COLOR_HASH_LEFT = "#7aa2f7"
COLOR_HASH_RIGHT = "#bb9af7"
COLOR_DATE = "#565f89"
COLOR_MSG = "#c0caf5"
COLOR_BADGE = "#e0af68"
COLOR_SELECTED = "#283457"
COLOR_DIM = "#565f89"


class ShowCommitDetail(Message):
    """Request to show full commit detail popup."""

    def __init__(self, commit: CommitInfo) -> None:
        self.commit = commit
        super().__init__()


class CommitMessageBar(Widget, can_focus=True):
    """Two-row commit message display for [ and ] cursors."""

    BINDINGS = [
        ("j", "toggle_focus", "Toggle row"),
        ("k", "toggle_focus", "Toggle row"),
        ("down", "toggle_focus", "Toggle row"),
        ("up", "toggle_focus", "Toggle row"),
        ("enter", "show_detail", "Show detail"),
        ("m", "show_detail", "Show detail"),
    ]

    focused_row: reactive[int] = reactive(0)  # 0 = left cursor row, 1 = right

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.left_commit: CommitInfo | None = None
        self.right_commit: CommitInfo | None = None

    def set_commits(self, left: CommitInfo | None, right: CommitInfo | None) -> None:
        self.left_commit = left
        self.right_commit = right
        self.refresh()

    def render(self) -> Text:
        text = Text()
        text.append(self._render_row(self.left_commit, "[", COLOR_HASH_LEFT, self.focused_row == 0))
        text.append("\n")
        text.append(self._render_row(self.right_commit, "]", COLOR_HASH_RIGHT, self.focused_row == 1))
        return text

    def _render_row(
        self, commit: CommitInfo | None, marker: str, hash_color: str, is_focused: bool
    ) -> Text:
        row = Text()

        if is_focused:
            row.append("▸ ", style="bold " + hash_color)
        else:
            row.append("  ")

        if commit is None:
            row.append(f"{marker} —", style=COLOR_DIM)
            return row

        row.append(f"{marker} ", style=hash_color)
        row.append(commit.short_hash, style=f"bold {hash_color}")
        row.append("  ", style="")
        row.append(commit.date.strftime("%Y-%m-%d %H:%M"), style=COLOR_DATE)
        row.append("  ", style="")

        # Truncate message
        first_line = commit.first_line
        max_msg_len = max(20, 60)
        if len(first_line) > max_msg_len:
            row.append(first_line[:max_msg_len] + "...", style=COLOR_MSG)
        else:
            row.append(first_line, style=COLOR_MSG)

        # Extra lines badge
        extra = commit.extra_lines
        if extra > 0:
            row.append(f"  +{extra} lines", style=f"italic {COLOR_BADGE}")

        # Stats
        row.append(f"  +{commit.additions}", style="#9ece6a")
        row.append(f" -{commit.deletions}", style="#f7768e")

        return row

    def action_toggle_focus(self) -> None:
        self.focused_row = 1 - self.focused_row
        self.refresh()

    def action_show_detail(self) -> None:
        commit = self.left_commit if self.focused_row == 0 else self.right_commit
        if commit:
            self.post_message(ShowCommitDetail(commit))
