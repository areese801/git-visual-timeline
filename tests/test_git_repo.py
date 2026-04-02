"""Tests for GitRepo wrapper using a temporary fixture repo."""

import os
import tempfile

import pytest
from git import Repo

from gvt.git.repo import GitRepo


@pytest.fixture
def fixture_repo():
    """Create a temporary git repo with known commit history."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Repo.init(tmpdir)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        # Commit 1: create file
        file_path = os.path.join(tmpdir, "hello.py")
        with open(file_path, "w") as f:
            f.write("print('hello')\n")
        repo.index.add(["hello.py"])
        repo.index.commit("Initial commit")

        # Commit 2: modify file
        with open(file_path, "w") as f:
            f.write("print('hello')\nprint('world')\n")
        repo.index.add(["hello.py"])
        repo.index.commit("Add world line")

        # Commit 3: add another file
        other_path = os.path.join(tmpdir, "other.py")
        with open(other_path, "w") as f:
            f.write("x = 1\n")
        repo.index.add(["other.py"])
        repo.index.commit("Add other file")

        # Commit 4: modify hello again
        with open(file_path, "w") as f:
            f.write("print('hello')\nprint('world')\nprint('!')\n")
        repo.index.add(["hello.py"])
        repo.index.commit("Add exclamation")

        yield tmpdir


def test_get_file_commits(fixture_repo):
    git_repo = GitRepo(fixture_repo)
    commits = git_repo.get_file_commits("hello.py")

    # hello.py was touched in commits 1, 2, 4 (not 3)
    assert len(commits) == 3
    # Oldest first
    assert commits[0].first_line == "Initial commit"
    assert commits[-1].first_line == "Add exclamation"


def test_get_file_commits_other(fixture_repo):
    git_repo = GitRepo(fixture_repo)
    commits = git_repo.get_file_commits("other.py")
    assert len(commits) == 1
    assert commits[0].first_line == "Add other file"


def test_get_diff(fixture_repo):
    git_repo = GitRepo(fixture_repo)
    commits = git_repo.get_file_commits("hello.py")
    diff = git_repo.get_diff("hello.py", commits[0].hexsha, commits[1].hexsha)
    assert "world" in diff


def test_get_tracked_files(fixture_repo):
    git_repo = GitRepo(fixture_repo)
    files = git_repo.get_tracked_files()
    assert "hello.py" in files
    assert "other.py" in files


def test_get_branches(fixture_repo):
    git_repo = GitRepo(fixture_repo)
    branches, current = git_repo.get_branches()
    assert current in branches


def test_commit_info_properties(fixture_repo):
    git_repo = GitRepo(fixture_repo)
    commits = git_repo.get_file_commits("hello.py")
    c = commits[0]
    assert len(c.short_hash) == 7
    assert c.first_line == "Initial commit"
    assert c.extra_lines == 0
