"""
gvt run against a repo from an untrusted source: control characters in commit
messages and file contents, markup-like and pathspec-like file names, non-ASCII
names, and a hostile .git/config.
"""

import os
import stat

import pytest
from git import Repo

from textual.content import Content

from gvt.app import GVTApp
from gvt.git.repo import GitRepo
from gvt.widgets.file_tree import FileTreeWidget
from gvt.widgets.timeline import TimelineWidget

ESC_TITLE = "\x1b]0;PWNED\x07"


def _write(repo_dir: str, path: str, text: str, mode: str = "w") -> None:
    full = os.path.join(repo_dir, path)
    os.makedirs(os.path.dirname(full) or repo_dir, exist_ok=True)
    with open(full, mode, newline="") as f:
        f.write(text)


@pytest.fixture
def hostile_repo(tmp_path):
    """
    A repo whose names, messages and contents try to attack the terminal and gvt.
    """
    repo_dir = str(tmp_path / "hostile")
    os.makedirs(repo_dir)
    repo = Repo.init(repo_dir)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", f"Mal{ESC_TITLE}lory")
        cw.set_value("user", "email", "m@example.com")

    _write(repo_dir, "normal.py", "a\n")
    _write(repo_dir, "[/]bad.py", "b\n")
    _write(repo_dir, "[red]styled.py", "c\n")
    _write(repo_dir, "café.py", "d\n")
    _write(repo_dir, "app/[slug]/page.tsx", "slug v1\n")
    _write(repo_dir, "app/s/page.tsx", "s v1\n")
    _write(repo_dir, "content.txt", "plain\r\nwindows line\r\n")
    repo.git.add("-A")
    repo.git.commit("-m", "[/] unbalanced close tag")

    _write(repo_dir, "normal.py", "a\na2\n")
    _write(repo_dir, "content.txt", f"plain\r\nwindows line\r\n{ESC_TITLE} hidden\n")
    repo.git.add("-A")
    repo.git.commit("-m", f"escape {ESC_TITLE} and \x1b[2J clear")

    _write(repo_dir, "app/s/page.tsx", "s v2\n")
    repo.git.add("-A")
    repo.git.commit("-m", "Only the s page")

    _write(repo_dir, "normal.py", "a\na2\na3\n")
    _write(repo_dir, "café.py", "d\nd2\n")
    repo.git.add("-A")
    repo.git.commit("-m", "Subject with ---GVT_START--- inside")
    return repo_dir


def _no_raw_controls(text: str) -> bool:
    return "\x1b" not in text and "\x07" not in text


class TestGitBoundary:
    def test_commit_messages_and_authors_are_safe(self, hostile_repo):
        repo = GitRepo(hostile_repo)
        commits = repo.get_file_commits("normal.py") + repo.get_all_commits()
        assert commits
        for c in commits:
            assert _no_raw_controls(c.message), c.message
            assert _no_raw_controls(c.author), c.author
        assert any("\\x1b]0;PWNED\\x07" in c.message for c in commits)

    def test_file_contents_and_diffs_are_safe(self, hostile_repo):
        repo = GitRepo(hostile_repo)
        commits = repo.get_file_commits("content.txt")
        diff = repo.get_diff("content.txt", commits[0].hexsha, commits[-1].hexsha)
        content = repo.get_file_at_commit("content.txt", commits[-1].hexsha)
        assert "PWNED" in diff and _no_raw_controls(diff)
        assert "PWNED" in content and _no_raw_controls(content)
        assert "\r" not in content
        assert _no_raw_controls(repo.get_file_content("content.txt"))

    def test_blame_and_contributors_are_safe(self, hostile_repo):
        repo = GitRepo(hostile_repo)
        sha = repo.get_file_commits("normal.py")[-1].hexsha
        assert all(_no_raw_controls(author) for _, author, _ in repo.get_blame("normal.py", sha))
        assert all(_no_raw_controls(name) for name, _ in repo.get_file_contributors("normal.py"))

    def test_paths_are_literal_not_pathspecs(self, hostile_repo):
        repo = GitRepo(hostile_repo)
        slug = repo.get_file_commits("app/[slug]/page.tsx")
        assert [c.message for c in slug] == ["[/] unbalanced close tag"]
        s_commits = repo.get_file_commits("app/s/page.tsx")
        assert len(s_commits) == 2
        diff = repo.get_diff("app/[slug]/page.tsx", s_commits[0].hexsha, s_commits[-1].hexsha)
        assert "s v2" not in diff

    def test_non_ascii_file_names(self, hostile_repo):
        repo = GitRepo(hostile_repo)
        assert "café.py" in repo.get_tracked_files()
        assert len(repo.get_file_commits("café.py")) == 2
        newest = repo.get_all_commits()[0]
        assert ("café.py", 1, 0) in repo.get_commit_files(newest.hexsha)

    def test_record_marker_in_subject_does_not_break_parsing(self, hostile_repo):
        repo = GitRepo(hostile_repo)
        newest = repo.get_all_commits()[0]
        assert newest.message == "Subject with ---GVT_START--- inside"
        assert (newest.additions, newest.deletions) == (2, 0)
        normal = repo.get_file_commits("normal.py")
        assert normal[-1].message == "Subject with ---GVT_START--- inside"
        assert normal[-1].additions == 1

    def test_control_characters_in_file_names_never_reach_output(self, tmp_path):
        repo_dir = str(tmp_path / "ctlnames")
        os.makedirs(repo_dir)
        repo = Repo.init(repo_dir)
        with repo.config_writer() as cw:
            cw.set_value("user", "name", "T")
            cw.set_value("user", "email", "t@example.com")
        _write(repo_dir, f"evil{ESC_TITLE}.txt", "x\n")
        repo.git.add("-A")
        repo.git.commit("-m", "init")
        gvt = GitRepo(repo_dir)
        listed = gvt.get_tracked_files() + [f[0] for f in gvt.get_commit_files(gvt.get_all_commits()[0].hexsha)]
        assert listed and all(_no_raw_controls(path) for path in listed)

    def test_markup_named_paths_listed(self, hostile_repo):
        files = GitRepo(hostile_repo).get_tracked_files()
        assert "[/]bad.py" in files and "[red]styled.py" in files


def _marker_script(tmp_path, name: str) -> tuple[str, str]:
    marker = str(tmp_path / f"{name}.ran")
    script = tmp_path / f"{name}.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script), marker


class TestHostileGitConfig:
    def test_external_diff_and_textconv_do_not_run(self, hostile_repo, tmp_path):
        ext, ext_marker = _marker_script(tmp_path, "extdiff")
        conv, conv_marker = _marker_script(tmp_path, "textconv")
        _write(hostile_repo, ".gitattributes", "*.py diff=evil\n")
        repo = Repo(hostile_repo)
        with repo.config_writer() as cw:
            cw.set_value("diff", "external", ext)
            cw.set_value('diff "evil"', "textconv", conv)
        gvt = GitRepo(hostile_repo)
        commits = gvt.get_file_commits("normal.py")
        assert "a2" in gvt.get_diff("normal.py", commits[0].hexsha, commits[-1].hexsha)
        gvt.get_blame("normal.py", commits[-1].hexsha)
        _write(hostile_repo, "normal.py", "changed\n")
        gvt.has_uncommitted_changes("normal.py")
        gvt.get_diff_to_working_tree("normal.py", commits[-1].hexsha)
        assert not os.path.exists(ext_marker)
        assert not os.path.exists(conv_marker)

    def test_fsmonitor_does_not_run(self, hostile_repo, tmp_path):
        hook, marker = _marker_script(tmp_path, "fsmonitor")
        with Repo(hostile_repo).config_writer() as cw:
            cw.set_value("core", "fsmonitor", hook)
        gvt = GitRepo(hostile_repo)
        gvt.get_untracked_files()
        gvt.has_uncommitted_changes("normal.py")
        gvt.get_commit_files(gvt.get_all_commits()[0].hexsha)
        assert not os.path.exists(marker)


class TestApp:
    SIZE = (120, 40)

    @pytest.mark.parametrize("path", ["[/]bad.py", "[red]styled.py", "normal.py", "café.py"])
    async def test_opening_hostile_files_does_not_crash(self, hostile_repo, path):
        app = GVTApp(repo_path=hostile_repo, initial_file=path)
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            for key in ("h", "l", "B", "c"):
                await pilot.press(key)
                await pilot.pause()
            assert app.is_running
            assert app.current_file == path
            assert app.query_one("#timeline-widget", TimelineWidget).commits

    async def test_border_title_shows_path_literally(self, hostile_repo):
        app = GVTApp(repo_path=hostile_repo, initial_file="[red]styled.py")
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            title = app.query_one("#diff-pane").border_title
            # Rendered, the title must still show the brackets, not apply a style
            assert "[red]styled.py" in Content.from_markup(str(title)).plain

    async def test_tree_labels_show_names_literally(self, hostile_repo):
        app = GVTApp(repo_path=hostile_repo)
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.pause()
            tree = app.query_one(FileTreeWidget)._tree
            labels = [str(child.label) for child in tree.root.children]
            assert "[red]styled.py" in labels


class TestEvolutionHostile:
    SIZE = (130, 40)

    async def test_evolution_on_markup_named_file(self, hostile_repo):
        from gvt.widgets.evolution_screen import EvolutionScreen
        from gvt.widgets.modals import CommitSearchModal

        app = GVTApp(repo_path=hostile_repo, initial_file="[/]bad.py")
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.press("v")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert isinstance(app.screen, EvolutionScreen)
            title = str(app.screen.query_one("#evolution-container").border_title)
            assert "[/]bad.py" in Content.from_markup(title).plain
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, CommitSearchModal)
            await pilot.press("X")
            await pilot.pause()
            assert app.is_running

    def test_rule_text_with_control_characters_is_printed_safely(self, hostile_repo):
        from gvt.exclusions import Exclusions, describe

        _write(hostile_repo, ".gvt.toml", '[evolution]\nexclude = ["evil\\u001b]0;X\\u0007/"]\n')
        text = describe(Exclusions.load(hostile_repo, user_config=None))
        assert "evil" in text
        assert _no_raw_controls(text)
# Characters git passes through raw with core.quotePath=false: C1 controls and
# bidi overrides (these can reorder or control what a terminal shows)
UNSAFE_DISPLAY = ("‮", "\x9b", "⁦")


def _display_safe(text: str) -> bool:
    return not any(ch in text for ch in UNSAFE_DISPLAY) and _no_raw_controls(text)


@pytest.fixture
def unicode_tricks_repo(tmp_path):
    repo_dir = str(tmp_path / "tricks")
    os.makedirs(repo_dir)
    repo = Repo.init(repo_dir)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@example.com")
    _write(repo_dir, "bidi‮txt.py", "x\n")
    _write(repo_dir, "c1\x9bname.py", "y\n")
    repo.git.add("-A")
    repo.git.commit("-m", "init")
    repo.git.tag("v1‮rtl")
    return repo_dir


class TestDisplayedNames:
    SIZE = (120, 40)

    def test_ref_names_are_safe(self, unicode_tricks_repo):
        commits = GitRepo(unicode_tricks_repo).get_all_commits()
        assert "v1" in commits[0].refs
        assert _display_safe(commits[0].refs)

    async def test_file_names_with_c1_and_bidi_are_shown_escaped(self, unicode_tricks_repo):
        from gvt.widgets.changed_files import ChangedFilesWidget
        from gvt.widgets.status_bar import GVTStatusBar

        path = "bidi‮txt.py"
        app = GVTApp(repo_path=unicode_tricks_repo, initial_file=path)
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.current_file == path  # the real name still opens the file

            title = Content.from_markup(str(app.query_one("#diff-pane").border_title)).plain
            assert "bidi" in title and _display_safe(title)

            tree = app.query_one(FileTreeWidget)._tree
            labels = [str(child.label) for child in tree.root.children]
            assert labels and all(_display_safe(label) for label in labels)

            status = app.query_one(GVTStatusBar)._render_info_line().plain
            assert "bidi" in status and _display_safe(status)

            changed = app.query_one(ChangedFilesWidget)
            rendered = " ".join(line.plain for line in changed._lines)
            assert "bidi" in rendered and _display_safe(rendered)

    async def test_commit_files_picker_shows_names_escaped(self, unicode_tricks_repo):
        from gvt.widgets.modals import CommitFilesModal

        app = GVTApp(repo_path=unicode_tricks_repo)
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.pause()
            app._all_commits_cache = app.git_repo.get_all_commits()
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, CommitFilesModal)
            text = " ".join(str(s.render()) for s in app.screen.query("Static"))
            assert "bidi" in text and _display_safe(text)


def test_far_future_commit_dates_do_not_crash(tmp_path):
    repo_dir = str(tmp_path / "future")
    os.makedirs(repo_dir)
    repo = Repo.init(repo_dir)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@example.com")
    _write(repo_dir, "a.txt", "x\n")
    repo.git.add("a.txt")
    stamp = "@300000000000 +0000"  # year 11476
    repo.git.commit("-m", "far", env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
    gvt = GitRepo(repo_dir)
    commits = gvt.get_file_commits("a.txt") + gvt.get_all_commits()
    assert commits and all(c.date.year == 2100 for c in commits)
    # Blame shows local dates; the clamped instant is 2100-01-01 00:00 UTC
    assert gvt.get_blame("a.txt", commits[0].hexsha)[0][2] == commits[0].date.astimezone().strftime("%Y-%m-%d")
