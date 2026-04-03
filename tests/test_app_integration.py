"""Integration tests for the full GVT app using Textual's async test framework."""

import os
import time

import pytest
from git import Repo

from gvt.app import GVTApp
from gvt.widgets.timeline import TimelineWidget
from gvt.widgets.diff_view import DiffViewWidget
from gvt.widgets.file_tree import FileTreeWidget
from gvt.widgets.changed_files import ChangedFilesWidget
from gvt.widgets.commit_bar import CommitMessageBar


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
    async with app.run_test(size=(120, 40)) as pilot:
        assert app.is_running


@pytest.mark.asyncio
async def test_file_tree_shows_files(app_repo):
    app = make_app(app_repo)
    async with app.run_test(size=(120, 40)) as pilot:
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
