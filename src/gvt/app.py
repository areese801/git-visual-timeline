"""Main GVT Textual application."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from git.exc import GitCommandError
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.markup import escape

from gvt.git.cache import DiffCache
from gvt.git.repo import CommitInfo, GitRepo
from gvt.logging_setup import get_logger
from gvt.textsafe import safe_name

from gvt.widgets.changed_files import ChangedFilesWidget, ChangedFileSelected, ChangedFileHighlighted
from gvt.widgets.commit_bar import CommitMessageBar, ShowCommitDetail
from gvt.widgets.diff_view import MODE_FULL, DiffContextChanged, DiffViewWidget
from gvt.widgets.evolution_screen import EvolutionScreen
from gvt.widgets.file_tree import FileSelected, FileTreeWidget
from gvt.widgets.modals import (
    CommitDetailPopup,
    CommitFilesModal,
    CommitSearchModal,
    FileSearchModal,
    HelpModal,
    QuitConfirmModal,
    TimeFilterModal,
)
from gvt.widgets.status_bar import GVTStatusBar
from gvt.widgets.timeline import CursorMoved, TimelineWidget


log = get_logger(__name__)


class GVTApp(App):
    """Git Visual Timeline TUI application."""

    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("1", "focus_pane(1)", "Files", show=False),
        Binding("2", "focus_pane(2)", "Timeline", show=False),
        Binding("3", "focus_pane(3)", "Commits", show=False),
        Binding("4", "focus_pane(4)", "Diff", show=False),
        Binding("5", "focus_pane(5)", "Changed files", show=False),
        Binding("tab", "focus_next_pane", "Next pane", show=False),
        Binding("shift+tab", "focus_prev_pane", "Prev pane", show=False),
        Binding("q", "confirm_quit", "Quit"),
        Binding("escape", "confirm_quit", "Quit", show=False),
        Binding("question_mark", "show_help", "Help", show=False),
        Binding("c", "commit_search", "Commit search", show=False),
        Binding("f", "file_search", "File search", show=False),
        Binding("ctrl+p", "file_search", "File search", show=False),
        Binding("t", "time_filter", "Time filter", show=False),
        Binding("w", "toggle_whole_file", "Whole file", show=False),
        Binding("b", "toggle_blame", "Blame", show=False),
        Binding("d", "toggle_side_by_side", "Side-by-side diff", show=False),
        Binding("B", "flash_last_author", "Last author", show=False),
        Binding("n", "global_next_hunk", "Next hunk", show=False),
        Binding("p", "global_prev_hunk", "Prev hunk", show=False),
        Binding("N", "global_prev_hunk", "Prev hunk", show=False),
        Binding("P", "global_next_hunk", "Next hunk", show=False),
        Binding("slash", "global_search_diff", "Search diff", show=False),
        Binding("y", "copy_short_hash", "Copy hash", show=False),
        Binding("Y", "copy_full_hash", "Copy full hash", show=False),
        Binding("e", "open_in_editor", "Open in editor", show=False),
        Binding("v", "evolution", "Evolution", show=False),
        Binding("ctrl+h", "focus_left", "Focus left", show=False),
        # Terminals send Ctrl+h as the Backspace byte, which Textual reads as
        # backspace; text inputs still get Backspace first
        Binding("backspace", "focus_left", "Focus left", show=False),
        Binding("ctrl+l", "focus_right", "Focus right", show=False),
        Binding("ctrl+k", "focus_up", "Focus up", show=False),
        Binding("ctrl+j", "focus_down", "Focus down", show=False),
    ]

    # App actions that stay available while the Evolution screen is open
    _EVOLUTION_ALLOWED_ACTIONS = {"confirm_quit", "show_help"}

    def __init__(self, repo_path: str, initial_file: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.repo_path = repo_path
        self.initial_file = initial_file
        self.git_repo = GitRepo(repo_path)
        self.diff_cache = DiffCache(max_size=100)
        self.current_file: str | None = None
        self.current_commits: list[CommitInfo] = []
        self._q_count: int = 0
        self._q_timer = None
        self._all_commits_cache: list[CommitInfo] | None = None
        self._selection_generation = 0
        self._file_generation = 0
        # (file, sha) to put the timeline cursor on once that file loads
        self._pending_focus: tuple[str, str] | None = None
        self._pane_order = [
            "file-tree-widget",
            "timeline-widget",
            "commit-bar",
            "diff-view",
            "changed-files",
        ]
        self._current_pane_idx = 0

    def compose(self) -> ComposeResult:
        tracked_files = self.git_repo.get_tracked_files()
        untracked_files = self.git_repo.get_untracked_files()

        with Horizontal():
            with Vertical(id="left-pane"):
                with Container(id="file-tree-pane"):
                    yield FileTreeWidget(tracked_files, untracked_files, id="file-tree-widget")

                with Container(id="changed-files-pane"):
                    yield ChangedFilesWidget(id="changed-files")

            with Vertical(id="right-pane"):
                with Container(id="timeline-pane"):
                    yield TimelineWidget(id="timeline-widget")

                with Container(id="commit-bar-pane"):
                    yield CommitMessageBar(id="commit-bar")

                with Container(id="diff-pane"):
                    yield DiffViewWidget(id="diff-view")

        yield GVTStatusBar()

    def on_mount(self) -> None:
        self.query_one("#file-tree-pane", Container).border_title = "[1] Files"
        self.query_one("#timeline-pane", Container).border_title = "[2] Timeline"
        self.query_one("#commit-bar-pane", Container).border_title = "[3] Commits"
        self.query_one("#diff-pane", Container).border_title = "[4] Diff"
        self.query_one("#changed-files-pane", Container).border_title = "[5] Changed"

        branch = self.git_repo.get_current_branch()
        status_bar = self.query_one(GVTStatusBar)
        status_bar.update_info(branch=branch)
        status_bar.set_focused_pane("file-tree-widget")

        if self.initial_file:
            rel_path = self.initial_file
            if os.path.isabs(rel_path):
                rel_path = os.path.relpath(rel_path, self.repo_path)
            self._save_last_file(rel_path)
            self._load_file(rel_path)
        else:
            last = self._read_last_file()
            if last and os.path.isfile(os.path.join(self.repo_path, last)):
                self._load_file(last)
            else:
                self.query_one("#file-tree-widget", FileTreeWidget).focus()

    def on_descendant_focus(self, event) -> None:
        """Track which pane is focused and update status bar legend."""
        # Focus can land inside a pane (the Files pane focuses its inner tree),
        # so use the nearest pane that contains the focused widget
        for node in (event.widget, *event.widget.ancestors):
            if node.id in self._pane_order:
                self._current_pane_idx = self._pane_order.index(node.id)
                self.query_one(GVTStatusBar).set_focused_pane(node.id)
                return

    def _last_file_path(self) -> Path:
        """Return the path to the last-file marker for this repo."""
        repo_hash = hashlib.md5(self.repo_path.encode()).hexdigest()
        return Path.home() / ".config" / "gvt" / f"{repo_hash}.last"

    def _save_last_file(self, rel_path: str) -> None:
        """Persist the last-selected file for this repo."""
        p = self._last_file_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(os.fsencode(rel_path))
        except OSError as error:
            log.debug("Could not save last file: %s", error)

    def _read_last_file(self) -> str | None:
        """Read the last-selected file for this repo, or None."""
        p = self._last_file_path()
        try:
            value = os.fsdecode(p.read_bytes())
        except OSError:
            return None
        return value if value and "\0" not in value else None

    @on(FileSelected)
    def on_file_selected(self, event: FileSelected) -> None:
        if event.tracked:
            self._save_last_file(event.path)
            self._load_file(event.path)
        else:
            self._load_untracked_file(event.path)

    @on(ChangedFileSelected)
    def on_changed_file_selected(self, event: ChangedFileSelected) -> None:
        self._save_last_file(event.path)
        self._load_file(event.path)

    @on(ChangedFileHighlighted)
    def on_changed_file_highlighted(self, event: ChangedFileHighlighted) -> None:
        self.query_one("#changed-files-pane", Container).border_title = f"[5] {escape(safe_name(event.path))}"

    def _load_untracked_file(self, file_path: str) -> None:
        """Show an untracked file as a read-only preview."""
        self._selection_generation += 1
        self._file_generation += 1
        self.current_file = file_path
        self.current_commits = []

        timeline = self.query_one("#timeline-widget", TimelineWidget)
        commit_bar = self.query_one("#commit-bar", CommitMessageBar)
        diff_view = self.query_one("#diff-view", DiffViewWidget)
        changed_files = self.query_one("#changed-files", ChangedFilesWidget)
        status_bar = self.query_one(GVTStatusBar)

        timeline.set_commits([])
        commit_bar.set_commits(None, None)
        changed_files.clear()

        content = self.git_repo.get_file_content(file_path)
        if content:
            diff_view.set_preview(content)
        else:
            diff_view.set_message("Unable to read file")

        branch = self.git_repo.get_current_branch()
        status_bar.update_info(file_path=file_path, branch=branch)
        self.query_one("#timeline-pane", Container).border_title = "[2] Timeline"
        self.query_one("#diff-pane", Container).border_title = f"[4] Preview {escape(safe_name(file_path))} (untracked)"
        self.query_one("#changed-files-pane", Container).border_title = "[5] Changed"

        # Focus the diff pane so user can scroll the preview
        diff_view.focus()
        self._current_pane_idx = 3

    def _clear_selection(self, file_path: str, message: str) -> None:
        self._selection_generation += 1
        self.query_one(CommitMessageBar).set_commits(None, None)
        self.query_one(ChangedFilesWidget).clear()
        self.query_one(DiffViewWidget).set_message(message)
        self.query_one("#changed-files-pane", Container).border_title = "[5] Changed"
        self.query_one("#diff-pane", Container).border_title = "[4] Diff"
        self.query_one(GVTStatusBar).update_info(file_path, branch=self.git_repo.get_current_branch())

    def _load_file(self, file_path: str, focus_sha: str | None = None) -> None:
        """
        Start async loading of a file's commit history.

        :param file_path: Repo-relative file to load.
        :param focus_sha: Commit to put the timeline cursor on once loaded
            (defaults to the newest commit).
        """
        self._file_generation += 1
        self.current_file = file_path
        self.current_commits = []
        self.query_one("#timeline-pane", Container).border_title = "[2] Timeline"
        self.query_one(TimelineWidget).set_commits([])
        self._clear_selection(file_path, "Loading history…")
        self._pending_focus = (file_path, focus_sha) if focus_sha else None
        self.notify("Loading history...", timeout=10)
        self._do_load_file(file_path, self._file_generation)

    @work(thread=True)
    def _do_load_file(
        self, file_path: str, generation: int, refresh: bool = False
    ) -> None:
        """Load file commits in background thread."""
        commits = self.git_repo.get_file_commits(file_path)

        # Append WIP tick if file has uncommitted changes
        if commits:
            try:
                if self.git_repo.has_uncommitted_changes(file_path):
                    adds, dels = self.git_repo.get_working_tree_stats(file_path)
                    wip_commit = CommitInfo(
                        hexsha="0000000000000000000000000000000000000000",
                        date=datetime.now(tz=timezone.utc),
                        author="(working tree)",
                        message="Uncommitted changes",
                        additions=adds,
                        deletions=dels,
                        is_wip=True,
                    )
                    commits.append(wip_commit)
            except GitCommandError as e:
                log.warning("WIP probe for %s failed: %s", file_path, e)

        self.call_from_thread(self._apply_loaded_file, file_path, commits, generation, refresh)

    def _apply_loaded_file(
        self,
        file_path: str,
        commits: list[CommitInfo],
        generation: int,
        refresh: bool = False,
    ) -> None:
        """Apply loaded commits to the UI (runs on main thread)."""
        if self._file_generation != generation:
            return
        self.clear_notifications()

        timeline = self.query_one("#timeline-widget", TimelineWidget)
        if refresh:
            timeline.refresh_commits(commits)
            self.current_commits = timeline.commits
            if self.current_commits:
                self._update_from_timeline(timeline, file_path)
            else:
                self._clear_selection(file_path, "No commits in this period")
            return
        self.current_commits = commits
        if not commits:
            self._clear_selection(file_path, "No commits found for this file")
            return

        timeline.set_commits(self.current_commits)
        if self._pending_focus and self._pending_focus[0] == file_path:
            focus_sha = self._pending_focus[1]
            for idx, commit in enumerate(self.current_commits):
                if commit.hexsha == focus_sha:
                    timeline.cursor = idx
                    break
        self._pending_focus = None
        self._update_from_timeline(timeline, file_path)

        timeline.focus()
        self._current_pane_idx = 1

    @on(CursorMoved)
    def on_cursor_moved(self, event: CursorMoved) -> None:
        if not self.current_file or not self.current_commits:
            return
        timeline = self.query_one("#timeline-widget", TimelineWidget)
        self._update_from_timeline(timeline, self.current_file)

        # Show commit toast while scrubbing — clear previous first
        self.clear_notifications()
        commit = self.current_commits[timeline.cursor]
        if commit.is_wip:
            title = "WIP"
        else:
            title = f"{commit.short_hash}  {commit.date.astimezone().strftime('%Y-%m-%d')}  {commit.author}  +{commit.additions} -{commit.deletions}"
        # Commit text comes from the repo: show it literally, not as markup
        self.notify(
            commit.message.strip(),
            title=title,
            timeout=2,
            markup=False,
        )

    def _update_from_timeline(self, timeline: TimelineWidget, file_path: str) -> None:
        """Update commit bar, diff, changed files, and status bar from timeline state."""
        left_idx = timeline.left_cursor
        right_idx = timeline.right_cursor

        commit_bar = self.query_one("#commit-bar", CommitMessageBar)
        left_commit = self.current_commits[left_idx] if left_idx < len(self.current_commits) else None
        right_commit = self.current_commits[right_idx] if right_idx < len(self.current_commits) else None
        commit_bar.set_commits(left_commit, right_commit)

        current_commit = self.current_commits[timeline.cursor]
        if current_commit.is_wip:
            self.query_one("#diff-pane", Container).border_title = f"[4] Diff {escape(safe_name(file_path))} (WIP)"
            self.query_one("#changed-files-pane", Container).border_title = "[5] Uncommitted changes"
        else:
            self.query_one("#diff-pane", Container).border_title = f"[4] Diff {escape(safe_name(file_path))}"
            self.query_one("#changed-files-pane", Container).border_title = f"[5] Also changed on {current_commit.short_hash}"

        self._selection_generation += 1
        generation = self._selection_generation
        diff_view = self.query_one(DiffViewWidget)
        diff_view.set_message("Loading diff…")
        self.query_one(ChangedFilesWidget).clear()
        self._load_diff(file_path, left_commit, right_commit, diff_view.context_lines, generation)
        if not current_commit.is_wip:
            self._update_changed_files(current_commit, generation)
        if diff_view.blame_enabled and not right_commit.is_wip:
            self._load_blame(
                self._revision_path(file_path, right_commit),
                right_commit.hexsha,
                generation,
            )

        branch = self.git_repo.get_current_branch()
        if timeline.has_pins:
            pos = f"{left_idx + 1}→{right_idx + 1}/{len(self.current_commits)}"
        else:
            pos = f"{timeline.cursor + 1}/{len(self.current_commits)}"
        status_bar = self.query_one(GVTStatusBar)
        status_bar.update_info(
            file_path=file_path,
            commit_position=pos,
            branch=branch,
            additions=right_commit.additions if right_commit else 0,
            deletions=right_commit.deletions if right_commit else 0,
        )

    @staticmethod
    def _revision_path(current_path: str, commit: CommitInfo) -> str:
        return commit.files[0][0] if commit.files else current_path

    def _apply_if_current(self, generation: int, callback, *args) -> None:
        if self._selection_generation == generation:
            callback(*args)

    @work(thread=True, exclusive=True, group="changed-files")
    def _update_changed_files(self, commit: CommitInfo, generation: int) -> None:
        files = self.git_repo.get_commit_files(commit.hexsha)
        self.call_from_thread(self._apply_if_current, generation, self._show_changed_files, files)

    def _show_changed_files(self, files: list[tuple[str, int, int]]) -> None:
        self.query_one(ChangedFilesWidget).set_files(files)

    def _commit_diff(
        self, file_path: str, left: CommitInfo, right: CommitInfo, context: int
    ) -> str:
        left_path = self._revision_path(file_path, left)
        right_path = self._revision_path(file_path, right)
        return self.diff_cache.get_or_compute(
            file_path,
            f"{left.hexsha}_ctx{context}",
            right.hexsha,
            lambda: self.git_repo.get_diff(
                right_path, left.hexsha, right.hexsha, context, previous_path=left_path
            ),
        )

    @work(thread=True, exclusive=True, group="diff")
    def _load_diff(
        self,
        file_path: str,
        left: CommitInfo,
        right: CommitInfo,
        context: int,
        generation: int,
    ) -> None:
        diff = ""
        message = "No changes between selected commits for this file"
        if left.hexsha == right.hexsha:
            message = "Same commit selected for both cursors"
        elif left.is_wip:
            message = "Cannot diff from WIP backwards"
        elif right.is_wip:
            diff = self.git_repo.get_diff_to_working_tree(
                file_path,
                left.hexsha,
                context,
                previous_path=self._revision_path(file_path, left),
            )
        else:
            diff = self._commit_diff(file_path, left, right, context)
        needs_content = self.call_from_thread(
            self._show_diff, generation, context, diff, message
        )
        if needs_content:
            content = (
                self.git_repo.get_file_content(file_path)
                if right.is_wip
                else self.git_repo.get_file_at_commit(
                    self._revision_path(file_path, right), right.hexsha
                )
            )
            self.call_from_thread(
                self._show_content, generation, context, content, diff
            )

    def _show_diff(
        self, generation: int, context: int, diff: str, message: str
    ) -> bool:
        view = self.query_one(DiffViewWidget)
        if generation != self._selection_generation or context != view.context_lines:
            return False
        if diff:
            view.set_diff(diff)
            timeline = self.query_one(TimelineWidget)
            self._preload_adjacent_diffs(
                self.current_file,
                timeline.cursor,
                view.context_lines,
                self.current_commits,
            )
            return view.view_mode == MODE_FULL
        else:
            view.set_message(message)
            return False

    def _show_content(
        self, generation: int, context: int, content: str, diff: str
    ) -> None:
        view = self.query_one(DiffViewWidget)
        if generation == self._selection_generation and context == view.context_lines:
            view.set_full_file(content, diff)

    @work(thread=True, exclusive=True, group="preload")
    def _preload_adjacent_diffs(
        self, file_path: str, cursor_idx: int, context: int, commits: list[CommitInfo]
    ) -> None:
        """Preload diffs for adjacent timeline positions into the cache."""
        if not commits or len(commits) < 2:
            return

        # Adjacent pairs to preload: (N-1 → N) and (N → N+1)
        pairs = []
        if cursor_idx > 0:
            pairs.append((cursor_idx - 1, cursor_idx))
        if cursor_idx < len(commits) - 1:
            pairs.append((cursor_idx, cursor_idx + 1))

        for left_idx, right_idx in pairs:
            if self.current_file != file_path:
                return

            left = commits[left_idx]
            right = commits[right_idx]

            if left.hexsha == right.hexsha or left.is_wip or right.is_wip:
                continue

            self._commit_diff(file_path, left, right, context)

    @on(DiffContextChanged)
    def on_diff_context_changed(self, event: DiffContextChanged) -> None:
        if not self.current_file or not self.current_commits:
            return
        timeline = self.query_one("#timeline-widget", TimelineWidget)
        self._load_diff(
            self.current_file,
            self.current_commits[timeline.left_cursor],
            self.current_commits[timeline.right_cursor],
            event.context_lines,
            self._selection_generation,
        )

    @on(ShowCommitDetail)
    def on_show_commit_detail(self, event: ShowCommitDetail) -> None:
        self.push_screen(CommitDetailPopup(event.commit))

    def action_focus_pane(self, pane_num: int) -> None:
        idx = pane_num - 1
        if 0 <= idx < len(self._pane_order):
            self._current_pane_idx = idx
            widget_id = self._pane_order[idx]
            try:
                widget = self.query_one(f"#{widget_id}")
                widget.focus()
            except NoMatches:
                log.debug("focus_pane: widget #%s not present", widget_id)

    def action_focus_next_pane(self) -> None:
        self._current_pane_idx = (self._current_pane_idx + 1) % len(self._pane_order)
        self.action_focus_pane(self._current_pane_idx + 1)

    def action_focus_prev_pane(self) -> None:
        self._current_pane_idx = (self._current_pane_idx - 1) % len(self._pane_order)
        self.action_focus_pane(self._current_pane_idx + 1)

    # Pane layout:  [1] Files   (top-left)    | [2] Timeline  (top-right)
    #               [5] Changed (bottom-left) | [3] Commits   (mid-right)
    #                                         | [4] Diff      (main-right)
    _LEFT_PANES = [0, 4]     # indices: file-tree-widget=0, changed-files=4
    _RIGHT_PANES = [1, 2, 3]  # indices: timeline=1, commit-bar=2, diff-view=3

    @staticmethod
    def _tmux_select_pane(direction: str) -> None:
        """Hand off navigation to tmux if running inside tmux."""
        if os.environ.get("TMUX"):
            try:
                subprocess.run(["tmux", "select-pane", f"-{direction}"], check=False)
            except OSError as e:
                log.warning("tmux pane handoff failed: %s", e)

    def action_focus_left(self) -> None:
        if self._current_pane_idx in self._LEFT_PANES:
            self._tmux_select_pane("L")
            return
        self.action_focus_pane(1)  # Files

    def action_focus_right(self) -> None:
        if self._current_pane_idx in self._RIGHT_PANES:
            self._tmux_select_pane("R")
            return
        self.action_focus_pane(2)  # Timeline

    def action_focus_up(self) -> None:
        if self._current_pane_idx in self._RIGHT_PANES:
            idx_in = self._RIGHT_PANES.index(self._current_pane_idx)
            if idx_in > 0:
                self.action_focus_pane(self._RIGHT_PANES[idx_in - 1] + 1)
            else:
                self._tmux_select_pane("U")
        elif self._current_pane_idx in self._LEFT_PANES:
            idx_in = self._LEFT_PANES.index(self._current_pane_idx)
            if idx_in > 0:
                self.action_focus_pane(self._LEFT_PANES[idx_in - 1] + 1)
            else:
                self._tmux_select_pane("U")

    def action_focus_down(self) -> None:
        if self._current_pane_idx in self._RIGHT_PANES:
            idx_in = self._RIGHT_PANES.index(self._current_pane_idx)
            if idx_in < len(self._RIGHT_PANES) - 1:
                self.action_focus_pane(self._RIGHT_PANES[idx_in + 1] + 1)
            else:
                self._tmux_select_pane("D")
        elif self._current_pane_idx in self._LEFT_PANES:
            idx_in = self._LEFT_PANES.index(self._current_pane_idx)
            if idx_in < len(self._LEFT_PANES) - 1:
                self.action_focus_pane(self._LEFT_PANES[idx_in + 1] + 1)
            else:
                self._tmux_select_pane("D")

    def action_confirm_quit(self) -> None:
        self._q_count += 1
        if self._q_count >= 2:
            # qq — immediate exit
            self.exit()
            return

        # First q — wait briefly for a possible second
        if self._q_timer is not None:
            self._q_timer.stop()

        self._q_timer = self.set_timer(0.4, self._show_quit_confirm)

    def _show_quit_confirm(self) -> None:
        self._q_count = 0
        self._q_timer = None

        def on_result(confirmed) -> None:
            if confirmed:
                self.exit()

        self.push_screen(QuitConfirmModal(), callback=on_result)

    def action_time_filter(self) -> None:
        timeline = self.query_one("#timeline-widget", TimelineWidget)

        def on_result(result) -> None:
            if result is None:
                return
            timeline.apply_time_filter(result)
            if self.current_file:
                self.current_commits = timeline.commits
                if self.current_commits:
                    self._update_from_timeline(timeline, self.current_file)
                else:
                    self._clear_selection(self.current_file, "No commits in this period")
                if result:
                    self.query_one("#timeline-pane", Container).border_title = f"[2] Timeline (since {result})"
                else:
                    self.query_one("#timeline-pane", Container).border_title = "[2] Timeline"

        self.push_screen(TimeFilterModal(timeline.time_filter), callback=on_result)

    def action_show_help(self) -> None:
        self.push_screen(HelpModal())

    def action_commit_search(self) -> None:
        if self._all_commits_cache:
            self._show_commit_search_modal(self._all_commits_cache)
        else:
            self.notify("Loading commits...", timeout=10)
            self._do_commit_search()

    @work(thread=True)
    def _do_commit_search(self) -> None:
        all_commits = self.git_repo.get_all_commits()
        self._all_commits_cache = all_commits
        self.call_from_thread(self.clear_notifications)
        if not all_commits:
            return
        self.call_from_thread(self._show_commit_search_modal, all_commits)

    def _show_commit_search_modal(self, all_commits: list[CommitInfo]) -> None:

        def on_commit_selected(result) -> None:
            if result is None or not isinstance(result, tuple):
                return
            action, idx = result
            if action != "select":
                return

            commit = all_commits[idx]
            # Get files changed in this commit and show file picker
            files = self.git_repo.get_commit_files(commit.hexsha)
            if not files:
                return

            def on_file_selected(result) -> None:
                if result is not None:
                    self._load_file(result, focus_sha=commit.hexsha)

            self.push_screen(
                CommitFilesModal(commit, files),
                callback=on_file_selected,
            )

        self.push_screen(CommitSearchModal(all_commits, title="Search recent commits (up to 500, excluding merges)"), callback=on_commit_selected)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """
        Disable pane actions while the Evolution screen is open (their widgets
        aren't on screen); quit and help stay available.
        """
        if action in self._EVOLUTION_ALLOWED_ACTIONS:
            return True
        app_actions = {b.action.split("(")[0] for b in self.BINDINGS}
        if action in app_actions and any(isinstance(s, EvolutionScreen) for s in self.screen_stack):
            return False
        return True

    def _resolve_evolution_scope(self) -> tuple[str, str, bool, str | None]:
        """
        Pick what the Evolution screen covers.

        The highlighted file-tree node when the tree has focus, otherwise the
        file loaded in the timeline, otherwise the whole repo. Untracked nodes
        fall back to the whole repo, with a note saying why.

        :returns: (scope path, label, is_file, note to show or None)
        """
        scope: tuple[str, bool] | None = None
        note = None
        tree = self.query_one("#file-tree-widget", FileTreeWidget)
        if tree.has_focus_within:
            scope = tree.cursor_scope()
            if scope is None and tree.cursor_is_untracked():
                note = "Untracked files have no history yet, so this shows the whole repo."
        elif self.current_file and self.current_commits:
            scope = (self.current_file, True)

        path, is_file = scope or (".", False)
        if path == ".":
            return ".", "whole repo", False, note
        label = safe_name(path) if is_file else safe_name(path.rstrip("/")) + "/"
        return path, label, is_file, note

    def action_evolution(self) -> None:
        scope, label, is_file, note = self._resolve_evolution_scope()
        time_filter = self.query_one("#timeline-widget", TimelineWidget).time_filter
        if note:
            self.notify(note, timeout=4, markup=False)

        def on_result(result) -> None:
            if result is None:
                return
            path, sha = result
            self._save_last_file(path)
            self._load_file(path, focus_sha=sha)

        self.push_screen(
            EvolutionScreen(self.git_repo, scope, label, is_file, time_filter),
            callback=on_result,
        )

    def action_file_search(self) -> None:
        tracked_files = self.git_repo.get_tracked_files()

        def on_result(result) -> None:
            if result is not None:
                self._load_file(result)

        self.push_screen(FileSearchModal(tracked_files), callback=on_result)

    def action_global_search_diff(self) -> None:
        diff_view = self.query_one("#diff-view", DiffViewWidget)
        diff_view.focus()
        self._current_pane_idx = 3
        diff_view.action_start_search()

    def action_global_next_hunk(self) -> None:
        diff_view = self.query_one("#diff-view", DiffViewWidget)
        diff_view.focus()
        self._current_pane_idx = 3
        diff_view.action_next_hunk()

    def action_global_prev_hunk(self) -> None:
        diff_view = self.query_one("#diff-view", DiffViewWidget)
        diff_view.focus()
        self._current_pane_idx = 3
        diff_view.action_prev_hunk()

    def action_toggle_whole_file(self) -> None:
        self.query_one("#diff-view", DiffViewWidget).action_toggle_full_file()

    def action_toggle_side_by_side(self) -> None:
        diff_view = self.query_one("#diff-view", DiffViewWidget)
        diff_view.action_toggle_side_by_side()
        status_bar = self.query_one(GVTStatusBar)
        status_bar.diff_mode = "side-by-side" if diff_view.side_by_side else "inline"
        status_bar.refresh()

    def action_toggle_blame(self) -> None:
        diff_view = self.query_one("#diff-view", DiffViewWidget)
        diff_view.action_toggle_blame()
        if diff_view.blame_enabled and self.current_file and self.current_commits:
            timeline = self.query_one("#timeline-widget", TimelineWidget)
            right_commit = self.current_commits[timeline.right_cursor]
            if not right_commit.is_wip:
                self._load_blame(self._revision_path(self.current_file, right_commit), right_commit.hexsha, self._selection_generation)

    def action_flash_last_author(self) -> None:
        """Show who last modified the file and contributor breakdown."""
        if not self.current_file or not self.current_commits:
            return
        timeline = self.query_one("#timeline-widget", TimelineWidget)
        commit = self.current_commits[timeline.cursor]
        contributors = self.git_repo.get_file_contributors(self.current_file)

        # Build contributor text for notification (no modal — avoids ghosting)
        total = sum(count for _, count in contributors)
        lines = [f"Last modified by {commit.author}  ({commit.short_hash})"]
        if total:
            lines.append("")
            for name, count in contributors[:8]:
                pct = count / total * 100
                bar = "█" * max(1, round(count / total * 20))
                lines.append(f"  {bar} {name}  {count} commits ({pct:.0f}%)")
        self.clear_notifications()
        self.notify("\n".join(lines), title="Contributors", timeout=5, markup=False)

    def action_copy_short_hash(self) -> None:
        if not self.current_commits:
            return
        timeline = self.query_one("#timeline-widget", TimelineWidget)
        commit = self.current_commits[timeline.cursor]
        self._copy_to_clipboard(commit.short_hash)

    def action_copy_full_hash(self) -> None:
        if not self.current_commits:
            return
        timeline = self.query_one("#timeline-widget", TimelineWidget)
        commit = self.current_commits[timeline.cursor]
        self._copy_to_clipboard(commit.hexsha)

    def _copy_to_clipboard(self, text: str) -> None:
        try:
            if shutil.which("pbcopy"):
                subprocess.run(["pbcopy"], input=text.encode(), check=True)
            elif shutil.which("xclip"):
                subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
            elif shutil.which("xsel"):
                subprocess.run(["xsel", "--clipboard", "--input"], input=text.encode(), check=True)
            else:
                self.notify("No clipboard tool found", timeout=2)
                return
            self.notify(f"Copied {text}", timeout=2)
        except (subprocess.CalledProcessError, OSError) as e:
            log.warning("clipboard copy failed: %s", e)
            self.notify("Failed to copy to clipboard", timeout=2)

    def action_open_in_editor(self) -> None:
        if not self.current_file:
            return
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vim"
        file_path = os.path.join(self.repo_path, self.current_file)
        result = None
        with self.suspend():
            try:
                # $EDITOR may carry arguments, e.g. "code --wait"
                result = subprocess.run(shlex.split(editor) + [file_path])
            except (OSError, ValueError) as e:
                log.warning("editor %s failed to launch: %s", editor, e)
        if result is None:
            self.notify(f"Could not launch editor: {editor}", timeout=3, markup=False)
        elif result.returncode != 0:
            log.warning("editor %s exited with code %d", editor, result.returncode)
            self.notify(f"Editor exited with code {result.returncode}", timeout=2)

        elif self.is_running:
            if self.current_file in self.query_one(FileTreeWidget).untracked_files:
                self._load_untracked_file(self.current_file)
            else:
                self._file_generation += 1
                self._do_load_file(
                    self.current_file, self._file_generation, refresh=True
                )

    @work(thread=True, exclusive=True, group="blame")
    def _load_blame(self, file_path: str, commit_sha: str, generation: int) -> None:
        blame_data = self.git_repo.get_blame(file_path, commit_sha)
        self.call_from_thread(
            self._apply_if_current, generation, self._show_blame, blame_data
        )

    def _show_blame(self, blame: list[tuple[str, str, str]]) -> None:
        self.query_one(DiffViewWidget).set_blame(blame)
