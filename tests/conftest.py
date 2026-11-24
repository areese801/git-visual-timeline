"""Shared test fixtures for gvt test suite."""

import os
import tempfile
import time

import pytest
from git import Repo

from gvt.app import GVTApp
from gvt.git.repo import GitRepo


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path, monkeypatch):
    """
    Keep tests away from the developer's ~/.config/gvt: no personal config is
    read, and the "last file" marker is written to the test's temp dir.
    """
    monkeypatch.setenv("GVT_CONFIG", str(tmp_path / "no-user-config.toml"))
    monkeypatch.setattr(GVTApp, "_last_file_path", lambda self: tmp_path / "gvt-last-file")


@pytest.fixture(autouse=True)
def close_git_repos(monkeypatch):
    """
    Close every GitPython Repo a test opens.

    Each Repo keeps `git cat-file` processes and their pipes open until it is
    garbage collected, so a full run can pass macOS's default limit of 256 open
    files ("Too many open files").
    """
    opened = []
    original_init = Repo.__init__

    def tracking_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        opened.append(self)

    monkeypatch.setattr(Repo, "__init__", tracking_init)
    yield
    for repo in opened:
        repo.close()


@pytest.fixture
def fixture_repo(tmp_path):
    """
    Create a temporary git repo with rich known history for testing.

    Structure:
      - hello.py: created in commit 1, modified in 2 and 4
      - README.md: created in commit 3
      - src/app.py: created in commit 5, modified in commit 6
      - An untracked file: untracked.txt

    Commits (chronological):
      1. "Initial commit" - hello.py (1 line)
      2. "Add world line" - hello.py (2 lines)
      3. "Add README" - README.md
      4. "Add exclamation" - hello.py (3 lines)
      5. "Add app module" - src/app.py (3 lines)
      6. "Update app module" - src/app.py (4 lines), also modifies hello.py

    Authors:
      Commits 1-5: "Test User <test@test.com>"
      Commit 6: "Other Dev <other@dev.com>"
    """
    repo_dir = str(tmp_path / "repo")
    os.makedirs(repo_dir)
    repo = Repo.init(repo_dir)
    repo.config_writer().set_value("user", "name", "Test User").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()

    # Commit 1: create hello.py
    hello_path = os.path.join(repo_dir, "hello.py")
    with open(hello_path, "w") as f:
        f.write("print('hello')\n")
    repo.index.add(["hello.py"])
    repo.index.commit("Initial commit")
    time.sleep(0.1)

    # Commit 2: modify hello.py
    with open(hello_path, "w") as f:
        f.write("print('hello')\nprint('world')\n")
    repo.index.add(["hello.py"])
    repo.index.commit("Add world line")
    time.sleep(0.1)

    # Commit 3: add README.md
    readme_path = os.path.join(repo_dir, "README.md")
    with open(readme_path, "w") as f:
        f.write("# Test Project\n\nThis is a test.\n")
    repo.index.add(["README.md"])
    repo.index.commit("Add README")
    time.sleep(0.1)

    # Commit 4: modify hello.py again
    with open(hello_path, "w") as f:
        f.write("print('hello')\nprint('world')\nprint('!')\n")
    repo.index.add(["hello.py"])
    repo.index.commit("Add exclamation")
    time.sleep(0.1)

    # Commit 5: add src/app.py
    src_dir = os.path.join(repo_dir, "src")
    os.makedirs(src_dir)
    app_path = os.path.join(src_dir, "app.py")
    with open(app_path, "w") as f:
        f.write("def main():\n    print('app')\n    return 0\n")
    repo.index.add(["src/app.py"])
    repo.index.commit("Add app module")
    time.sleep(0.1)

    # Commit 6: modify src/app.py and hello.py (different author)
    repo.config_writer().set_value("user", "name", "Other Dev").release()
    repo.config_writer().set_value("user", "email", "other@dev.com").release()
    with open(app_path, "w") as f:
        f.write("def main():\n    print('app v2')\n    return 0\n\ndef helper():\n    pass\n")
    with open(hello_path, "w") as f:
        f.write("print('hello')\nprint('world')\nprint('!')\nprint('done')\n")
    repo.index.add(["src/app.py", "hello.py"])
    repo.index.commit("Update app and hello")
    time.sleep(0.1)

    # Reset author back
    repo.config_writer().set_value("user", "name", "Test User").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()

    # Create an untracked file
    untracked_path = os.path.join(repo_dir, "untracked.txt")
    with open(untracked_path, "w") as f:
        f.write("I am untracked\n")

    yield repo_dir


@pytest.fixture
def git_repo(fixture_repo):
    """Return a GitRepo instance wrapping the fixture repo."""
    return GitRepo(fixture_repo)


@pytest.fixture
def fixture_app(fixture_repo):
    """Return a GVTApp instance against the fixture repo."""
    return GVTApp(repo_path=fixture_repo)
