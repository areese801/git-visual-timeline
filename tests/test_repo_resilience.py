"""Tests verifying GitRepo degrades gracefully on bad input / corrupt state."""

import os

from git import Repo

from gvt.git.repo import GitRepo


def test_get_file_at_commit_unknown_sha(git_repo):
    """Unknown sha returns empty string rather than raising."""
    assert git_repo.get_file_at_commit("hello.py", "deadbeef" * 5) == ""


def test_get_file_at_commit_missing_path(git_repo):
    """Valid sha but missing path returns empty string."""
    commits = git_repo.get_file_commits("hello.py")
    assert git_repo.get_file_at_commit("does-not-exist.py", commits[-1].hexsha) == ""


def test_get_blame_unknown_sha(git_repo):
    """Unknown sha returns empty list."""
    assert git_repo.get_blame("hello.py", "deadbeef" * 5) == []


def test_get_blame_missing_file(git_repo):
    """Missing path returns empty list."""
    commits = git_repo.get_file_commits("hello.py")
    assert git_repo.get_blame("does-not-exist.py", commits[-1].hexsha) == []


def test_get_commit_files_unknown_sha(git_repo):
    """Unknown sha returns empty list."""
    assert git_repo.get_commit_files("deadbeef" * 5) == []


def test_build_ref_map_tolerates_corrupt_ref(fixture_repo):
    """A corrupt refs/heads/* file must not prevent history from loading."""
    bad_ref = os.path.join(fixture_repo, ".git", "refs", "heads", "bad-ref")
    with open(bad_ref, "w") as f:
        f.write("not-a-sha\n")

    gr = GitRepo(fixture_repo)
    commits = gr.get_file_commits("hello.py")
    assert len(commits) >= 1

    # get_all_commits also uses _build_ref_map
    all_commits = gr.get_all_commits()
    assert len(all_commits) >= 1


def test_get_branches_detached_head(fixture_repo):
    """Detached HEAD returns 'HEAD' as current branch."""
    r = Repo(fixture_repo)
    head_sha = r.head.commit.hexsha
    r.git.checkout(head_sha)  # detach

    gr = GitRepo(fixture_repo)
    _, current = gr.get_branches()
    assert current == "HEAD"
