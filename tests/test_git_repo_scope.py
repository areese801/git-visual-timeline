"""Tests for scoped commit logs and tag listing in GitRepo."""

import os

from git import Repo

from gvt.git.repo import GitRepo


def test_scope_root_returns_all_commits_newest_first(git_repo):
    commits = git_repo.get_scope_commits(".")
    assert len(commits) == 6
    assert commits[0].message == "Update app and hello"
    assert commits[-1].message == "Initial commit"


def test_scope_empty_string_means_whole_repo(git_repo):
    assert len(git_repo.get_scope_commits("")) == 6


def test_scope_directory_limits_commits(git_repo):
    commits = git_repo.get_scope_commits("src")
    assert [c.message for c in commits] == ["Update app and hello", "Add app module"]


def test_scope_directory_limits_stats_to_scope(git_repo):
    """
    Commit 6 touches src/app.py (+4 -1) and hello.py (+1); a src scope counts only app.py.
    """
    newest = git_repo.get_scope_commits("src")[0]
    assert (newest.additions, newest.deletions) == (4, 1)

    whole = git_repo.get_scope_commits(".")[0]
    assert (whole.additions, whole.deletions) == (5, 1)


def test_scope_single_file(git_repo):
    commits = git_repo.get_scope_commits("README.md")
    assert len(commits) == 1
    assert commits[0].message == "Add README"
    assert commits[0].additions == 3


def test_scope_unknown_path_returns_empty(git_repo):
    assert git_repo.get_scope_commits("no/such/dir") == []


def test_scope_accepts_absolute_path(git_repo, fixture_repo):
    commits = git_repo.get_scope_commits(os.path.join(fixture_repo, "src"))
    assert len(commits) == 2


def test_scope_cache_avoids_second_git_log(git_repo, monkeypatch):
    git_repo.get_scope_commits("src")
    calls = []
    original = git_repo._parse_log

    def counting_parse(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(git_repo, "_parse_log", counting_parse)
    git_repo.get_scope_commits("src")
    assert calls == []
    git_repo.get_scope_commits("hello.py")
    assert len(calls) == 1


def test_scope_cache_invalidated_by_new_commit(git_repo, fixture_repo):
    assert len(git_repo.get_scope_commits("src")) == 2

    repo = Repo(fixture_repo)
    with open(os.path.join(fixture_repo, "src", "new.py"), "w") as f:
        f.write("y = 2\n")
    repo.index.add(["src/new.py"])
    repo.index.commit("Add new module")

    commits = git_repo.get_scope_commits("src")
    assert len(commits) == 3
    assert commits[0].message == "Add new module"


def test_scope_cache_is_bounded(git_repo):
    for i in range(12):
        git_repo.get_scope_commits(f"missing-{i}")
    assert len(git_repo._scope_cache) <= 8


def test_scope_commits_in_empty_repo(tmp_path):
    repo_dir = str(tmp_path / "empty")
    Repo.init(repo_dir)
    assert GitRepo(repo_dir).get_scope_commits(".") == []


def test_head_sha(git_repo, fixture_repo):
    assert git_repo.get_head_sha() == Repo(fixture_repo).head.commit.hexsha


def test_head_sha_empty_repo(tmp_path):
    repo_dir = str(tmp_path / "empty")
    Repo.init(repo_dir)
    assert GitRepo(repo_dir).get_head_sha() is None


def test_get_all_commits_unchanged_by_shared_parser(git_repo):
    commits = git_repo.get_all_commits()
    assert len(commits) == 6
    assert commits[0].message == "Update app and hello"
    assert (commits[0].additions, commits[0].deletions) == (5, 1)


def test_get_tags_empty(git_repo):
    assert git_repo.get_tags() == []


def test_get_tags_lists_lightweight_and_annotated(git_repo, fixture_repo):
    repo = Repo(fixture_repo)
    commits = list(repo.iter_commits("HEAD", reverse=True))
    repo.create_tag("v0.1.0", ref=commits[1])
    repo.create_tag("v0.2.0", ref=commits[4], message="Release 0.2.0")

    tags = git_repo.get_tags()
    assert [t.name for t in tags] == ["v0.1.0", "v0.2.0"]
    assert tags[0].hexsha == commits[1].hexsha
    assert tags[1].hexsha == commits[4].hexsha
    assert tags[0].date <= tags[1].date


def test_scope_commits_carry_per_file_stats(git_repo):
    newest = git_repo.get_scope_commits(".")[0]
    assert sorted(newest.files) == [("hello.py", 1, 0), ("src/app.py", 4, 1)]
    assert newest.additions == sum(f[1] for f in newest.files)
    assert newest.deletions == sum(f[2] for f in newest.files)


def test_scope_commit_files_limited_to_scope(git_repo):
    newest = git_repo.get_scope_commits("src")[0]
    assert newest.files == [("src/app.py", 4, 1)]


def test_numstat_rename_paths_resolve_to_new_name():
    assert GitRepo._numstat_path("src/{old.py => new.py}") == "src/new.py"
    assert GitRepo._numstat_path("{a => b}/x.py") == "b/x.py"
    assert GitRepo._numstat_path("src/{ => gvt}/app.py") == "src/gvt/app.py"
    assert GitRepo._numstat_path("src/{gvt => }/app.py") == "src/app.py"
    assert GitRepo._numstat_path("old.py => new.py") == "new.py"
    assert GitRepo._numstat_path("plain.py") == "plain.py"


def test_scope_commits_handle_renames_and_binaries(git_repo, fixture_repo):
    repo = Repo(fixture_repo)
    repo.index.move(["README.md", "README.rst"])
    with open(os.path.join(fixture_repo, "logo.bin"), "wb") as f:
        f.write(bytes(range(256)))
    repo.index.add(["logo.bin"])
    repo.index.commit("Rename readme, add binary")

    newest = git_repo.get_scope_commits(".")[0]
    paths = dict((path, (adds, dels)) for path, adds, dels in newest.files)
    assert paths["logo.bin"] == (0, 0)
    assert "README.rst" in paths


def test_first_commit_date(git_repo, fixture_repo):
    first = list(Repo(fixture_repo).iter_commits("HEAD", reverse=True))[0]
    assert git_repo.get_first_commit_date() == first.authored_datetime.astimezone(
        git_repo.get_first_commit_date().tzinfo
    ).replace(microsecond=0)


def test_first_commit_date_empty_repo(tmp_path):
    repo_dir = str(tmp_path / "empty")
    Repo.init(repo_dir)
    assert GitRepo(repo_dir).get_first_commit_date() is None
