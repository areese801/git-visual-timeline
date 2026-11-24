"""Integration tests for the Evolution screen inside the full app."""

import os
from datetime import datetime, timezone

from git import Repo

from gvt.app import GVTApp
from gvt.git.repo import CommitInfo
from gvt.widgets.calendar_view import CalendarView
from gvt.widgets.file_tree import FileTreeWidget
from gvt.widgets.evolution_screen import EvolutionScreen, in_scope, summarize
from gvt.widgets.frequency_view import FrequencyView
from gvt.widgets.modals import CommitFilesModal, CommitSearchModal, ExclusionDetailsModal
from gvt.widgets.timeline import TimelineWidget

SIZE = (130, 40)


async def _settle(app, pilot) -> None:
    """Let workers finish and the UI catch up."""
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def _open_evolution(app, pilot) -> EvolutionScreen:
    await pilot.press("v")
    await _settle(app, pilot)
    assert isinstance(app.screen, EvolutionScreen)
    return app.screen


def test_in_scope():
    assert in_scope("src/app.py", ".")
    assert in_scope("src/app.py", "src")
    assert in_scope("src/app.py", "src/")
    assert in_scope("src/app.py", "src/app.py")
    assert not in_scope("srcs/x.py", "src")
    assert not in_scope("hello.py", "src")


async def test_v_from_tree_root_scopes_whole_repo(fixture_repo):
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        screen = await _open_evolution(app, pilot)
        assert (screen.scope, screen.scope_label, screen.scope_is_file) == (".", "whole repo", False)
        assert len(screen.commits) == 6
        calendar = screen.query_one(CalendarView)
        assert calendar.has_focus
        assert "6 commits" in calendar.status_text().plain


def test_summarize(git_repo):
    text = summarize(git_repo.get_scope_commits(".")).plain
    assert "6 commits" in text
    assert "2 authors" in text
    assert "1 active day" in text
    assert "+" in text and "−" in text
    assert summarize([]).plain == ""


async def test_v_from_tree_directory_scopes_directory(fixture_repo):
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        await pilot.press("j")  # root -> src/
        screen = await _open_evolution(app, pilot)
        assert (screen.scope, screen.scope_label, screen.scope_is_file) == ("src", "src/", False)
        assert len(screen.commits) == 2


async def test_v_from_timeline_scopes_current_file(fixture_repo):
    app = GVTApp(repo_path=fixture_repo, initial_file="hello.py")
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        assert isinstance(app.focused, TimelineWidget)
        screen = await _open_evolution(app, pilot)
        assert (screen.scope, screen.scope_is_file) == ("hello.py", True)
        assert len(screen.commits) == 4


async def test_escape_returns_and_restores_focus(fixture_repo):
    app = GVTApp(repo_path=fixture_repo, initial_file="hello.py")
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        await _open_evolution(app, pilot)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, EvolutionScreen)
        assert isinstance(app.focused, TimelineWidget)


async def test_pane_actions_disabled_while_open(fixture_repo):
    app = GVTApp(repo_path=fixture_repo, initial_file="hello.py")
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        assert app.check_action("toggle_blame", ())
        await _open_evolution(app, pilot)
        assert not app.check_action("toggle_blame", ())
        assert not app.check_action("time_filter", ())
        assert not app.check_action("evolution", ())
        assert app.check_action("confirm_quit", ())
        assert app.check_action("show_help", ())
        # Keys that would touch the hidden panes do nothing
        await pilot.press("b", "t", "w", "1")
        await pilot.pause()
        assert isinstance(app.screen, EvolutionScreen)


async def test_tab_and_number_keys_switch_views(fixture_repo):
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        screen = await _open_evolution(app, pilot)
        await pilot.press("tab")
        await pilot.pause()
        assert screen.query_one(FrequencyView).has_focus
        await pilot.press("1")
        await pilot.pause()
        assert screen.query_one(CalendarView).has_focus
        await pilot.press("2")
        await pilot.pause()
        assert screen.query_one(FrequencyView).has_focus
        await pilot.press("shift+tab")
        await pilot.pause()
        assert screen.query_one(CalendarView).has_focus


async def test_empty_scope_shows_message(fixture_repo):
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        app.push_screen(EvolutionScreen(app.git_repo, "nope", "nope/", False))
        await _settle(app, pilot)
        view = app.screen.query_one(CalendarView)
        assert "No commits touch nope/" in view.render().plain


async def test_time_filter_carried_into_title(fixture_repo):
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        app.push_screen(EvolutionScreen(app.git_repo, ".", "whole repo", False, time_filter="2000-01-01"))
        await _settle(app, pilot)
        assert "(since 2000-01-01)" in str(app.screen.query_one("#evolution-container").border_title)
        assert len(app.screen.commits) == 6


async def test_file_scope_jump_lands_on_chosen_commit(fixture_repo):
    app = GVTApp(repo_path=fixture_repo, initial_file="hello.py")
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        await _open_evolution(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, CommitSearchModal)
        # Newest first: Update app and hello, Add exclamation, ...
        await pilot.press("down", "enter")
        await _settle(app, pilot)
        assert not isinstance(app.screen, (EvolutionScreen, CommitSearchModal))
        timeline = app.query_one("#timeline-widget", TimelineWidget)
        assert app.current_file == "hello.py"
        assert timeline.commits[timeline.cursor].message == "Add exclamation"


async def test_directory_scope_jump_lists_in_scope_files_first(fixture_repo):
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        await pilot.press("j")  # src/
        await _open_evolution(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, CommitSearchModal)
        await pilot.press("enter")  # Update app and hello
        await pilot.pause()
        assert isinstance(app.screen, CommitFilesModal)
        assert [f[0] for f in app.screen.files] == ["src/app.py", "hello.py"]
        await pilot.press("enter")
        await _settle(app, pilot)
        timeline = app.query_one("#timeline-widget", TimelineWidget)
        assert app.current_file == "src/app.py"
        assert timeline.commits[timeline.cursor].message == "Update app and hello"


async def test_commit_search_lands_on_chosen_commit(fixture_repo):
    app = GVTApp(repo_path=fixture_repo, initial_file="README.md")
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        app._all_commits_cache = app.git_repo.get_all_commits()
        await pilot.press("c")
        await pilot.pause()
        # Newest first; index 4 = "Add world line" (touches hello.py only)
        await pilot.press("down", "down", "down", "down", "enter")
        await pilot.pause()
        assert isinstance(app.screen, CommitFilesModal)
        await pilot.press("enter")
        await _settle(app, pilot)
        timeline = app.query_one("#timeline-widget", TimelineWidget)
        assert app.current_file == "hello.py"
        assert timeline.commits[timeline.cursor].message == "Add world line"


async def test_jump_from_tree_keeps_tree_expanded(fixture_repo):
    """The Enter that closes the last modal must not also toggle the file tree."""
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        tree = app.query_one(FileTreeWidget)._tree
        assert tree.root.is_expanded
        await _open_evolution(app, pilot)
        await pilot.press("enter", "enter")
        await pilot.pause()
        await pilot.press("enter")
        await _settle(app, pilot)
        assert app.current_file is not None
        assert tree.root.is_expanded


async def test_commit_search_from_tree_keeps_tree_expanded(fixture_repo):
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        app._all_commits_cache = app.git_repo.get_all_commits()
        tree = app.query_one(FileTreeWidget)._tree
        await pilot.press("c")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await _settle(app, pilot)
        assert app.current_file is not None
        assert tree.root.is_expanded


async def test_unexpected_load_error_shows_message_not_crash(fixture_repo, monkeypatch):
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)

        def boom(path):
            raise OSError("disk went away")

        monkeypatch.setattr(app.git_repo, "get_scope_commits", boom)
        await pilot.press("v")
        await _settle(app, pilot)
        assert app.is_running
        assert isinstance(app.screen, EvolutionScreen)
        assert "Couldn't read history" in app.screen.query_one(CalendarView).render().plain


class _StubRepo:
    """Minimal GitRepo stand-in with fixed history."""

    def __init__(self, commits, root="/nonexistent-repo"):
        self.commits = commits
        self.root = root

    def get_scope_commits(self, path):
        return self.commits

    def get_tags(self):
        return []

    def get_first_commit_date(self):
        return min(c.date for c in self.commits) if self.commits else None


async def test_time_filter_passes_size_before_cutoff(fixture_repo):
    old = CommitInfo("a" * 40, datetime(2020, 1, 1, tzinfo=timezone.utc), "T", "old", 100, 20)
    new = CommitInfo("b" * 40, datetime.now(tz=timezone.utc), "T", "new", 5, 1)
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        app.push_screen(EvolutionScreen(_StubRepo([new, old]), ".", "whole repo", False, time_filter="1y"))
        await _settle(app, pilot)
        frequency = app.screen.query_one(FrequencyView)
        assert frequency.commits == [new]
        assert frequency.base_size == 80


async def test_legend_follows_the_active_view(fixture_repo):
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        screen = await _open_evolution(app, pilot)
        legend = screen.query_one("#evolution-legend")
        assert "year" in str(legend.render())
        await pilot.press("2")
        await pilot.pause()
        rendered = str(legend.render())
        assert "volume" in rendered and "year" not in rendered


def _add_lockfile_commits(repo_dir: str) -> None:
    """
    One commit touching code + a lockfile, one touching only the lockfile.
    """
    repo = Repo(repo_dir)
    with open(os.path.join(repo_dir, "pnpm-lock.yaml"), "w") as f:
        f.write("lock: 1\n" * 50)
    with open(os.path.join(repo_dir, "hello.py"), "a") as f:
        f.write("print('more')\n")
    repo.index.add(["pnpm-lock.yaml", "hello.py"])
    repo.index.commit("Add dependency")
    with open(os.path.join(repo_dir, "pnpm-lock.yaml"), "a") as f:
        f.write("lock: 2\n" * 20)
    repo.index.add(["pnpm-lock.yaml"])
    repo.index.commit("Bump lockfile")


async def test_authored_mode_drops_lockfile_lines_and_x_toggles(fixture_repo):
    _add_lockfile_commits(fixture_repo)
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        screen = await _open_evolution(app, pilot)
        assert screen.mode == "authored"
        assert len(screen.commits) == 7  # lockfile-only commit dropped
        newest = screen.commits[0]
        assert newest.message == "Add dependency"
        assert (newest.additions, newest.deletions) == (1, 0)
        summary = str(screen.query_one("#evolution-summary").render())
        assert summary.startswith("authored")
        assert "70 lines excluded" in summary

        await pilot.press("x")
        await pilot.pause()
        assert screen.mode == "everything"
        assert len(screen.commits) == 8
        assert str(screen.query_one("#evolution-summary").render()).startswith("everything")

        await pilot.press("x")
        await pilot.pause()
        assert len(screen.commits) == 7


async def test_shift_x_lists_rules(fixture_repo):
    _add_lockfile_commits(fixture_repo)
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        await _open_evolution(app, pilot)
        await pilot.press("X")
        await pilot.pause()
        assert isinstance(app.screen, ExclusionDetailsModal)
        text = app.screen.build_text().plain
        assert "Mode: authored" in text
        assert "· 70 (" in text and "in excluded files" in text
        assert "· 1 touched only excluded files" in text
        assert "What was excluded" in text
        assert "70 lines     1 file   preset:lockfiles  pnpm-lock.yaml" in text
        assert "             70  pnpm-lock.yaml" in text  # the file, under its rule
        assert "Largest files still counted" in text
        assert "README.md  → 'docs' preset" in text
        assert "How the rules were built" in text
        assert "✓ 1. Built-in presets" in text
        assert ".gvt.toml" in text and "not found" in text
        assert "Changing it" in text
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, EvolutionScreen)


async def test_x_in_details_toggles_mode_and_updates_text(fixture_repo):
    _add_lockfile_commits(fixture_repo)
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        screen = await _open_evolution(app, pilot)
        await pilot.press("X")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, ExclusionDetailsModal)

        await pilot.press("x")
        await pilot.pause()
        assert app.screen is modal  # still open
        assert screen.mode == "everything"
        assert len(screen.commits) == 8  # the charts behind it changed too
        shown = str(modal.query_one("#exclusion-details-text").render())
        assert "Mode: everything" in shown
        assert "are in files authored mode excludes" in shown
        assert "· 1 touched only files authored mode excludes" in shown
        assert "What authored mode excludes" in shown
        assert "Largest files counted now" in shown
        assert "x authored/all" in shown

        await pilot.press("x")
        await pilot.pause()
        assert screen.mode == "authored"
        assert len(screen.commits) == 7
        shown = str(modal.query_one("#exclusion-details-text").render())
        assert "Mode: authored" in shown
        assert "What was excluded" in shown


async def test_repo_config_sets_default_mode(fixture_repo):
    _add_lockfile_commits(fixture_repo)
    with open(os.path.join(fixture_repo, ".gvt.toml"), "w") as f:
        f.write('[evolution]\ndefault_mode = "everything"\n')
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        screen = await _open_evolution(app, pilot)
        assert screen.mode == "everything"
        assert len(screen.commits) == 8



def test_legend_fits_narrow_terminals_and_keeps_key_actions():
    from gvt.widgets.evolution_screen import legend_text

    wide = legend_text("frequency", 200).plain
    assert " X " in wide and " 0/$ " in wide and " Tab " in wide
    narrow = legend_text("frequency", 80).plain
    assert len(narrow) <= 80
    for key in (" x ", " X ", " m ", " Enter ", " Esc "):
        assert key in narrow
    assert " 0/$ " not in narrow
    calendar = legend_text("calendar", 80).plain
    assert len(calendar) <= 80 and " X " in calendar and " [ ] " in calendar


async def test_untracked_node_opens_whole_repo_with_a_note(fixture_repo, monkeypatch):
    app = GVTApp(repo_path=fixture_repo)
    notes = []
    original = app.notify
    monkeypatch.setattr(app, "notify", lambda msg, **k: notes.append(msg) or original(msg, **k))
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        tree = app.query_one(FileTreeWidget)._tree
        while tree.cursor_node.data != "__untracked_header__":
            await pilot.press("j")
        screen = await _open_evolution(app, pilot)
        assert screen.scope == "."
        assert any("Untracked" in note for note in notes)


async def test_u_widens_scope_to_parent_folders(fixture_repo):
    app = GVTApp(repo_path=fixture_repo, initial_file="src/app.py")
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        screen = await _open_evolution(app, pilot)
        assert (screen.scope, screen.scope_is_file) == ("src/app.py", True)
        await pilot.press("x")  # switch to everything; widening keeps the mode
        await pilot.press("u")
        await _settle(app, pilot)
        assert (screen.scope, screen.scope_label, screen.scope_is_file) == ("src", "src/", False)
        assert "src/" in str(screen.query_one("#evolution-container").border_title)
        assert screen.mode == "everything"
        await pilot.press("u")
        await _settle(app, pilot)
        assert (screen.scope, screen.scope_label) == (".", "whole repo")
        assert len(screen.commits) == 6
        await pilot.press("u")  # already the whole repo: stays put
        await _settle(app, pilot)
        assert screen.scope == "."


async def test_widen_ignores_results_for_an_older_scope(fixture_repo):
    app = GVTApp(repo_path=fixture_repo, initial_file="src/app.py")
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        screen = await _open_evolution(app, pilot)
        stale = list(screen._all_commits)
        # Called directly, so the new load can't land before the checks below
        screen.action_widen()
        assert screen._exclusions is None  # x and X wait for the new scope
        assert screen._all_commits == []
        # A late result for the file scope must not replace the folder's data
        screen._apply_history("src/app.py", stale, [], None, None, None)
        await _settle(app, pilot)
        assert screen.scope == "src" and len(screen.commits) == 2


async def test_scope_labels_and_details_show_names_safely(tmp_path):
    import os as _os

    from git import Repo as _Repo

    repo_dir = str(tmp_path / "r")
    _os.makedirs(repo_dir)
    repo = _Repo.init(repo_dir)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@example.com")
    path = "bidi‮txt.py"
    for name in (path, "yarn.lock"):
        with open(_os.path.join(repo_dir, name), "w") as f:
            f.write("x\n")
    repo.git.add("-A")
    repo.git.commit("-m", "init")
    repo.git.tag("v1‮rtl")

    app = GVTApp(repo_path=repo_dir, initial_file=path)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        screen = await _open_evolution(app, pilot)
        assert "‮" not in screen.scope_label
        assert all("‮" not in t.name for t in screen._tags)
        await pilot.press("u", "X")
        await _settle(app, pilot)
        text = app.screen.build_text().plain
        assert "yarn.lock" in text and "‮" not in text


async def test_details_counts_follow_the_mode(fixture_repo):
    _add_lockfile_commits(fixture_repo)
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        await _open_evolution(app, pilot)
        await pilot.press("X")
        await pilot.pause()
        modal = app.screen
        total = modal.result.total_lines
        text = modal.build_text().plain
        assert f"Counting {total - 70:,} of {total:,} changed lines" in text
        assert "Counting 7 of 8 commits" in text
        assert "pnpm-lock.yaml  excluded in authored mode" not in text

        await pilot.press("x")
        await pilot.pause()
        text = modal.build_text().plain
        assert f"Counting all {total:,} changed lines" in text
        assert "Counting all 8 commits" in text
        # Everything counts the lockfile, so it joins the largest files
        assert "pnpm-lock.yaml  excluded in authored mode" in text


async def test_widen_flashes_the_title_and_names_the_parent(fixture_repo):
    app = GVTApp(repo_path=fixture_repo, initial_file="src/app.py")
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        screen = await _open_evolution(app, pilot)
        container = screen.query_one("#evolution-container")
        assert "u  parent folder" in str(screen.query_one("#evolution-legend").render())
        assert not container.has_class("flash")
        await pilot.press("u")
        assert container.has_class("flash")
        await pilot.pause(2)
        assert not container.has_class("flash")


async def test_ctrl_hjkl_hands_off_to_tmux(fixture_repo, monkeypatch):
    moves = []
    monkeypatch.setattr(GVTApp, "_tmux_select_pane", staticmethod(moves.append))
    app = GVTApp(repo_path=fixture_repo)
    async with app.run_test(size=SIZE) as pilot:
        await _settle(app, pilot)
        screen = await _open_evolution(app, pilot)
        await pilot.press("ctrl+h", "ctrl+j", "ctrl+k", "ctrl+l")
        await pilot.pause()
        assert app.screen is screen
    assert moves == ["L", "D", "U", "R"]
