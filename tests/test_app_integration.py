"""Integration tests for the full GVT app using Textual's async test framework."""

import asyncio
import os
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest
from git import Repo

from gvt.app import GVTApp
from gvt.widgets.timeline import TimelineWidget
from gvt.widgets.diff_view import DiffViewWidget
from gvt.widgets.file_tree import FileTreeWidget
from gvt.widgets.changed_files import ChangedFilesWidget
from gvt.widgets.commit_bar import CommitMessageBar
from gvt.widgets.modals import CommitFilesModal, CommitSearchModal, FileSearchModal


@pytest.fixture
def app_repo(tmp_path):
    """Create a minimal git repo for app integration tests."""
    repo_dir = str(tmp_path / "app_repo")
    os.makedirs(repo_dir)
    repo = Repo.init(repo_dir)
    repo.config_writer().set_value("user", "name", "Test User").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()

    hello = os.path.join(repo_dir, "hello.py")
    with open(hello, "w") as f:
        f.write("print('hello')\n")
    repo.index.add(["hello.py"])
    repo.index.commit("Initial commit")
    time.sleep(0.1)

    with open(hello, "w") as f:
        f.write("print('hello')\nprint('world')\n")
    repo.index.add(["hello.py"])
    repo.index.commit("Add world")
    time.sleep(0.1)

    other = os.path.join(repo_dir, "other.py")
    with open(other, "w") as f:
        f.write("x = 1\n")
    repo.index.add(["other.py"])
    repo.index.commit("Add other")

    return repo_dir


def make_app(repo_dir, initial_file=None):
    return GVTApp(repo_path=repo_dir, initial_file=initial_file)


@pytest.mark.asyncio
async def test_app_launches(app_repo):
    app = make_app(app_repo)
    async with app.run_test(size=(120, 40)):
        assert app.is_running


@pytest.mark.asyncio
async def test_file_tree_shows_files(app_repo):
    app = make_app(app_repo)
    async with app.run_test(size=(120, 40)):
        tree = app.query_one("#file-tree-widget", FileTreeWidget)
        assert "hello.py" in tree.tracked_files
        assert "other.py" in tree.tracked_files


@pytest.mark.asyncio
async def test_selecting_file_populates_timeline(app_repo):
    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        timeline = app.query_one("#timeline-widget", TimelineWidget)
        assert len(timeline.commits) >= 2


@pytest.mark.asyncio
async def test_help_modal_opens_and_closes(app_repo):
    app = make_app(app_repo)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        assert len(app.screen_stack) > 1
        # Close it
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.asyncio
async def test_quit_double_tap(app_repo):
    app = make_app(app_repo)
    async with app.run_test(size=(120, 40)) as pilot:
        # qq should trigger immediate exit
        await pilot.press("q")
        await pilot.press("q")
        await pilot.pause()


@pytest.mark.asyncio
async def test_numbered_pane_switching(app_repo):
    app = make_app(app_repo)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        assert app._current_pane_idx == 1

        await pilot.press("4")
        await pilot.pause()
        assert app._current_pane_idx == 3


@pytest.mark.asyncio
async def test_file_search_opens_and_closes(app_repo):
    app = make_app(app_repo)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f")
        await pilot.pause()
        assert len(app.screen_stack) > 1
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.asyncio
async def test_commit_search_with_cache(app_repo):
    """Pre-populate cache to avoid async worker, then open commit search."""
    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        app._all_commits_cache = app.git_repo.get_all_commits()
        await pilot.press("c")
        await pilot.pause()
        assert len(app.screen_stack) > 1
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.asyncio
async def test_commit_search_select_shows_file_picker(app_repo):
    """Select a commit from search → CommitFilesModal should appear."""
    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        # Pre-populate cache
        all_commits = app.git_repo.get_all_commits()
        app._all_commits_cache = all_commits

        # Open commit search
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, CommitSearchModal), (
            f"Expected CommitSearchModal, got {type(app.screen).__name__}"
        )
        # Press Enter to select the first commit
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        # CommitFilesModal should now be on the screen stack
        assert isinstance(app.screen, CommitFilesModal), (
            f"Expected CommitFilesModal, got {type(app.screen).__name__}"
        )
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.asyncio
async def test_time_filter_opens_and_closes(app_repo):
    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        assert len(app.screen_stack) > 1
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.asyncio
async def test_whole_file_toggle(app_repo):
    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        diff_view = app.query_one("#diff-view", DiffViewWidget)
        assert diff_view.view_mode == "diff"
        await pilot.press("w")
        await pilot.pause()
        assert diff_view.view_mode == "full"


@pytest.mark.asyncio
async def test_blame_toggle(app_repo):
    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        diff_view = app.query_one("#diff-view", DiffViewWidget)
        assert diff_view.blame_enabled is False
        await pilot.press("b")
        await pilot.pause()
        assert diff_view.blame_enabled is True


@pytest.mark.asyncio
async def test_side_by_side_toggle(app_repo):
    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        diff_view = app.query_one("#diff-view", DiffViewWidget)
        assert diff_view.side_by_side is False
        await pilot.press("d")
        await pilot.pause()
        assert diff_view.side_by_side is True


@pytest.mark.asyncio
async def test_n_focuses_diff(app_repo):
    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert app._current_pane_idx == 3


@pytest.mark.asyncio
async def test_backspace_moves_focus_left_like_ctrl_h(app_repo):
    """Terminals send Ctrl+h as the Backspace byte, which Textual reads as backspace."""
    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("3")  # commits, a right-hand pane
        await pilot.press("backspace")
        await pilot.pause()
        assert app._current_pane_idx == 0
        assert app.focused in app.query_one(FileTreeWidget).query("*")


@pytest.mark.asyncio
async def test_backspace_still_edits_search_input(app_repo):
    from textual.widgets import Input

    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._all_commits_cache = app.git_repo.get_all_commits()
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, CommitSearchModal)
        await pilot.press("a", "b", "backspace")
        await pilot.pause()
        assert app.screen.query_one(Input).value == "a"
        assert isinstance(app.screen, CommitSearchModal)


@pytest.mark.asyncio
async def test_status_bar_shows_files_hints_when_files_pane_focused(app_repo):
    """Focus lands on the tree inside the Files pane; the legend must follow it."""
    from gvt.widgets.status_bar import GVTStatusBar

    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
        assert app.query_one(GVTStatusBar).focused_pane == "file-tree-widget"


async def test_delayed_diff_cannot_replace_untracked_preview(app_repo, monkeypatch):
    path = Path(app_repo) / "notes.txt"
    path.write_text("preview " + "x" * 200)
    app = make_app(app_repo)
    started = threading.Event()
    release = threading.Event()
    original = app.git_repo.get_diff

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(app.git_repo, "get_diff", delayed)
    async with app.run_test(size=(100, 35)) as pilot:
        app._load_file("hello.py")
        try:
            assert await asyncio.to_thread(started.wait, 5)
            app._load_untracked_file("notes.txt")
        finally:
            release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = app.query_one(DiffViewWidget)
        assert view.virtual_size.width >= 208
        view.action_toggle_full_file()
        assert "preview " in view._lines[0].plain


async def test_reopening_worktree_reloads_patch(app_repo):
    app = make_app(app_repo)
    path = Path(app_repo) / "hello.py"
    async with app.run_test(size=(100, 35)) as pilot:
        for value in ("first edit", "second edit"):
            path.write_text(value + "\n")
            app._load_file("hello.py")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "+" + value in app.query_one(DiffViewWidget).diff_text


async def test_empty_time_filter_clears_selectable_rows(app_repo):
    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        callbacks = []

        def open_filter(screen, callback):
            callbacks.append(callback)

        with patch.object(app, "push_screen", open_filter):
            app.action_time_filter()
        callbacks[0]("2099-01-01")
        assert app.query_one(ChangedFilesWidget).files == []
        assert app.query_one(CommitMessageBar).right_commit is None
        assert not app.query_one(DiffViewWidget).diff_text


async def test_pre_rename_commit_displays_historical_content(app_repo):
    repo = Repo(app_repo)
    target = repo.head.commit.parents[0].hexsha
    repo.index.move(["hello.py", "renamed.py"])
    repo.index.commit("Rename greeting")
    app = make_app(app_repo)
    async with app.run_test(size=(100, 35)) as pilot:
        app._load_file("renamed.py", focus_sha=target)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = app.query_one(DiffViewWidget)
        view.action_toggle_full_file()
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert "print('world')" in view._full_file_content


async def test_file_picker_highlights_results_beyond_first_fifty(app_repo):
    app = make_app(app_repo)
    files = [f"file-{index}" for index in range(60)]
    async with app.run_test(size=(90, 30)) as pilot:
        picker = FileSearchModal(files)
        app.push_screen(picker)
        await pilot.pause()
        picker.selected_idx = 55
        picker._update_results()
        await pilot.pause()
        labels = list(picker.query("#file-search-results Static"))
        assert any(
            "▸ file-55" in str(label.render())
            and label.region.overlaps(picker.query_one("#file-search-results").region)
            for label in labels
        )


async def test_editor_preserves_timeline_comparison(app_repo):
    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        timeline = app.query_one(TimelineWidget)
        timeline.apply_time_filter("1970-01-01")
        app.current_commits = timeline.commits
        timeline.cursor = 0
        timeline.pin_start = 0
        timeline.pin_end = 1
        view = app.query_one(DiffViewWidget)
        view.focus()
        with (
            patch.object(app, "suspend", nullcontext),
            patch("gvt.app.subprocess.run") as editor,
        ):
            editor.return_value.returncode = 0
            app.action_open_in_editor()
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert (
            timeline.time_filter,
            timeline.cursor,
            timeline.pin_start,
            timeline.pin_end,
        ) == ("1970-01-01", 0, 0, 1)
        assert app.focused is view


async def test_context_change_retains_changed_file_selection(app_repo):
    app = make_app(app_repo, initial_file="hello.py")
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        changed = app.query_one(ChangedFilesWidget)
        changed.set_files([("one", 1, 0), ("two", 1, 0)])
        changed.action_cursor_down()
        app.query_one(DiffViewWidget).action_more_context()
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert changed.selected_idx == 1


async def test_inline_diff_does_not_require_full_blob(app_repo, monkeypatch):
    app = make_app(app_repo, initial_file="hello.py")
    reads = []
    monkeypatch.setattr(
        app.git_repo,
        "get_file_at_commit",
        lambda *args: reads.append(args) or "content",
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        view = app.query_one(DiffViewWidget)
        assert view.diff_text and not reads
        view.action_toggle_full_file()
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert reads and view._full_file_content == "content"
