"""
Full-screen Evolution view: how a file, directory, or repo changed over time.
"""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from functools import partial

from git.exc import GitCommandError
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Static, TabbedContent, TabPane, Tabs

from gvt.evolution import bucket_by_day, local_day
from gvt.git.repo import CommitInfo, GitRepo, TagInfo
from gvt.logging_setup import get_logger
from gvt.widgets.calendar_view import CalendarView
from gvt.widgets.evolution_common import EvolutionView, PeriodChosen, plural
from gvt.widgets.frequency_view import FrequencyView
from gvt.widgets.modals import CommitFilesModal, CommitSearchModal
from gvt.widgets.timeline import parse_time_filter

log = get_logger(__name__)

# Tab pane id -> view widget id, in tab order
VIEWS = {
    "calendar": "calendar-view",
    "frequency": "frequency-view",
}

LEGEND = [
    ("Tab", "views"),
    ("h/j/k/l", "move"),
    ("[ ]", "year"),
    ("Enter", "commits"),
    ("?", "help"),
    ("Esc", "back"),
]


def summarize(commits: list[CommitInfo], tz: tzinfo | None = None) -> Text:
    """
    One-line overview of a scope: commits, +/−, active days, authors, span.
    """
    text = Text()
    if not commits:
        return text
    dim = "#565f89"
    days = bucket_by_day(commits, tz)
    authors = {c.author for c in commits}
    text.append(plural(len(commits), "commit"), style="#c0caf5")
    text.append("  ·  ", style=dim)
    text.append(f"+{sum(c.additions for c in commits):,}", style="#9ece6a")
    text.append(f" −{sum(c.deletions for c in commits):,}", style="#f7768e")
    for part in (
        plural(len(days), "active day"),
        plural(len(authors), "author"),
        f"{min(days).isoformat()} → {max(days).isoformat()}",
    ):
        text.append("  ·  ", style=dim)
        text.append(part, style="#c0caf5")
    return text


def in_scope(path: str, scope: str) -> bool:
    """
    True when a repo-relative path lies inside a scope ('.' = everything).
    """
    return scope == "." or path == scope or path.startswith(scope.rstrip("/") + "/")


class EvolutionScreen(Screen):
    """
    Tabbed calendar and frequency views for one scope.

    Dismisses with (file_path, commit_sha) when the user jumps into a file's
    history, or None on Esc.
    """

    DEFAULT_CSS = """
    EvolutionScreen {
        background: #1a1b26;
    }

    #evolution-container {
        height: 1fr;
        border: solid #7aa2f7;
        border-title-color: #7aa2f7;
        border-title-align: left;
    }

    #evolution-summary {
        height: 1;
        padding: 0 1;
    }

    #evolution-tabs {
        height: 1fr;
    }

    #evolution-tabs TabPane {
        padding: 1 1 0 1;
    }

    #evolution-tabs EvolutionView {
        height: 1fr;
    }

    #evolution-legend {
        height: 1;
        background: #1a1b26;
    }
    """

    BINDINGS = [
        ("escape", "close", "Back"),
        ("tab", "cycle_view(1)", "Next view"),
        ("shift+tab", "cycle_view(-1)", "Prev view"),
        ("1", "show_view('calendar')", "Calendar"),
        ("2", "show_view('frequency')", "Frequency"),
    ]

    def __init__(
        self,
        git_repo: GitRepo,
        scope: str,
        scope_label: str,
        scope_is_file: bool,
        time_filter: str = "",
        tz: tzinfo | None = None,
        **kwargs,
    ) -> None:
        """
        :param git_repo: Repo to read history from.
        :param scope: Repo-relative file or directory, or "." for the whole repo.
        :param scope_label: Human name for the scope shown in titles.
        :param scope_is_file: Whether Enter can jump straight to the scope file.
        :param time_filter: Active timeline filter ('3m', 'YYYY-MM-DD', '').
        :param tz: Time zone for day bucketing (None = local).
        """
        super().__init__(**kwargs)
        self.git_repo = git_repo
        self.scope = scope
        self.scope_label = scope_label
        self.scope_is_file = scope_is_file
        self.time_filter = time_filter
        self.tz = tz
        self.commits: list[CommitInfo] = []

    def compose(self) -> ComposeResult:
        with Container(id="evolution-container"):
            yield Static("", id="evolution-summary")
            with TabbedContent(id="evolution-tabs"):
                with TabPane("1 Calendar", id="calendar"):
                    yield CalendarView(tz=self.tz, id="calendar-view")
                with TabPane("2 Frequency", id="frequency"):
                    yield FrequencyView(tz=self.tz, id="frequency-view")
        legend = Text()
        for key, desc in LEGEND:
            legend.append(f" {key} ", style="bold #c0caf5 on #3b4261")
            legend.append(f" {desc} ", style="#565f89")
        yield Static(legend, id="evolution-legend")

    def on_mount(self) -> None:
        title = f"Evolution — {self.scope_label}"
        if self.time_filter:
            title += f" (since {self.time_filter})"
        self.query_one("#evolution-container", Container).border_title = title
        # Keep focus on the views so their keys work; Tab switches views instead
        self.query_one(Tabs).can_focus = False
        self._focus_active_view()
        self._load_history()

    # Data loading

    @work(thread=True, exclusive=True, group="evolution-load", exit_on_error=False)
    def _load_history(self) -> None:
        try:
            commits = self.git_repo.get_scope_commits(self.scope)
            tags = self.git_repo.get_tags()
        except (GitCommandError, OSError, ValueError) as e:
            log.warning("evolution history for %s failed: %s", self.scope, e)
            self.app.call_from_thread(self._show_message, "Couldn't read history (see log)")
            return

        cutoff = parse_time_filter(self.time_filter, datetime.now(tz=timezone.utc))
        if cutoff:
            commits = [c for c in commits if c.date >= cutoff]
        self.app.call_from_thread(self._apply_history, commits, tags)

    def _views(self) -> list[EvolutionView]:
        return list(self.query(EvolutionView))

    def _show_message(self, message: str) -> None:
        if not self.is_attached:
            return
        for view in self._views():
            view.set_message(message)

    def _apply_history(self, commits: list[CommitInfo], tags: list[TagInfo]) -> None:
        if not self.is_attached:
            return
        self.commits = commits
        if not commits:
            message = f"No commits touch {self.scope_label}"
            if self.time_filter:
                message += f" since {self.time_filter}"
            self._show_message(message)
            return
        self.query_one("#evolution-summary", Static).update(summarize(commits, self.tz))
        for view in self._views():
            view.set_data(commits, tags)

    # Tabs

    def _focus_active_view(self) -> None:
        active = self.query_one(TabbedContent).active or "calendar"
        self.query_one(f"#{VIEWS[active]}", EvolutionView).focus()

    @on(TabbedContent.TabActivated)
    def _on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self._focus_active_view()

    def action_show_view(self, pane_id: str) -> None:
        self.query_one(TabbedContent).active = pane_id
        self._focus_active_view()

    def action_cycle_view(self, step: int) -> None:
        ids = list(VIEWS)
        current = self.query_one(TabbedContent).active or ids[0]
        self.action_show_view(ids[(ids.index(current) + step) % len(ids)])

    def action_close(self) -> None:
        self.dismiss(None)

    # Jump to history

    @on(PeriodChosen)
    def _on_period_chosen(self, event: PeriodChosen) -> None:
        period = [c for c in self.commits if event.start <= local_day(c.date, self.tz) < event.end]
        if not period:
            self.notify(f"No commits in {event.label}", timeout=2)
            return
        title = f"Commits in {event.label} — {self.scope_label} (type to filter, Enter to select)"
        self.app.push_screen(
            CommitSearchModal(period, title=title),
            callback=partial(self._on_commit_picked, period),
        )

    def _on_commit_picked(self, period: list[CommitInfo], result) -> None:
        if not isinstance(result, tuple) or result[0] != "select":
            return
        commit = period[result[1]]

        if self.scope_is_file:
            self.dismiss((self.scope, commit.hexsha))
            return

        files = self.git_repo.get_commit_files(commit.hexsha)
        if not files:
            self.notify("No files changed in that commit", timeout=2)
            return
        ordered = sorted(files, key=lambda f: not in_scope(f[0], self.scope))

        def on_file_picked(path: str | None) -> None:
            if path is not None:
                self.dismiss((path, commit.hexsha))

        self.app.push_screen(CommitFilesModal(commit, ordered), callback=on_file_picked)
