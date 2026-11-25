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


def test_literal_arrow_and_white_space_are_preserved(git_repo, fixture_repo):
    repo = Repo(fixture_repo)
    path = " leading => trailing "
    with open(os.path.join(fixture_repo, path), "w") as stream:
        stream.write("data")
    repo.index.add([path])
    commit = repo.index.commit("Add unusual path")
    assert git_repo.get_commit_files(commit.hexsha) == [(path, 1, 0)]
    assert git_repo.get_scope_commits(".")[0].files == [(path, 1, 0)]


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


def test_file_scope_follows_renames(git_repo, fixture_repo):
    repo = Repo(fixture_repo)
    repo.index.move(["README.md", "GUIDE.md"])
    repo.index.commit("Rename README to GUIDE")
    messages = [c.message for c in git_repo.get_scope_commits("GUIDE.md")]
    assert messages[0] == "Rename README to GUIDE"
    assert "Add README" in messages  # from before the rename


def test_directory_scope_does_not_use_follow(git_repo):
    # --follow only works for a single file; a directory scope must still list everything
    assert len(git_repo.get_scope_commits("src")) == 2


def test_unborn_repo_lists_index_and_has_no_history(tmp_path):
    repo = Repo.init(tmp_path)
    (tmp_path / "staged").write_text("line\n")
    repo.index.add(["staged"])
    git = GitRepo(str(tmp_path))
    assert git.get_tracked_files() == ["staged"]
    assert git.get_file_commits("staged") == git.get_all_commits() == []


def test_history_preserves_message_body_and_pre_rename_stats(git_repo, fixture_repo):
    repo = Repo(fixture_repo)
    repo.index.move(["README.md", "GUIDE.md"])
    repo.index.commit("Rename guide\n\nBody with a tab\tand unicode.")
    history = git_repo.get_file_commits("GUIDE.md")
    assert history[0].additions == 3
    assert history[-1].extra_lines == 2
    assert "Body with a tab" in git_repo.get_all_commits()[0].searchable_text


def test_rename_comparison_excludes_reused_source_name(git_repo, fixture_repo):
    repo = Repo(fixture_repo)
    left = repo.head.commit.hexsha
    repo.index.move(["README.md", "guide.md"])
    repo.index.commit("Move guide")
    with open(os.path.join(fixture_repo, "README.md"), "w") as stream:
        stream.write("unrelated replacement\n")
    with open(os.path.join(fixture_repo, "guide.md"), "a") as stream:
        stream.write("guide update\n")
    repo.index.add(["README.md", "guide.md"])
    right = repo.index.commit("Update both files").hexsha
    for diff in (
        git_repo.get_diff("guide.md", left, right, previous_path="README.md"),
        git_repo.get_diff_to_working_tree("guide.md", left, previous_path="README.md"),
    ):
        assert "+guide update" in diff and "unrelated replacement" not in diff
    os.unlink(os.path.join(fixture_repo, "guide.md"))
    deleted = git_repo.get_diff_to_working_tree(
        "guide.md", left, previous_path="README.md"
    )
    assert "deleted file mode" in deleted and "unrelated replacement" not in deleted


def test_unchecked_out_file_follows_renames(git_repo, fixture_repo):
    repo = Repo(fixture_repo)
    repo.index.move(["README.md", "guide.md"])
    repo.index.commit("Move guide")
    os.unlink(os.path.join(fixture_repo, "guide.md"))
    assert "Add README" in [c.message for c in git_repo.get_scope_commits("guide.md")]


def test_blame_recognizes_long_object_ids(git_repo, monkeypatch):
    first, second = "1" * 64, "2" * 64
    output = f"{first} 1 1 1\nauthor First\n\tone\n{second} 2 2 1\nauthor Second\n\ttwo"
    monkeypatch.setattr(
        type(git_repo.repo.git), "blame", lambda *args, **kwargs: output, raising=False
    )
    assert git_repo.get_blame("hello.py", first) == [
        (first[:7], "First", ""),
        (second[:7], "Second", ""),
    ]


def test_log_skips_invalid_timestamp_and_its_stats():
    first, second = "1" * 40, "2" * 40
    records = [
        f"{first}\n0\nA\nfirst",
        "1\t0\tgood",
        f"{second}\n\nB\nsecond",
        "3\t0\tother",
    ]
    commits = GitRepo._parse_log("\0".join(records), {})
    assert [(c.hexsha, c.files) for c in commits] == [(first, [("good", 1, 0)])]
