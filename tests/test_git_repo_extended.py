"""Extended tests for GitRepo wrapper."""

import os

from gvt.git.repo import GitRepo


def test_get_all_commits_newest_first(git_repo):
    commits = git_repo.get_all_commits()
    assert len(commits) == 6
    # newest first
    assert commits[0].first_line == "Update app and hello"
    assert commits[-1].first_line == "Initial commit"


def test_get_all_commits_dates_descending(git_repo):
    commits = git_repo.get_all_commits()
    for i in range(len(commits) - 1):
        assert commits[i].date >= commits[i + 1].date


def test_get_file_at_commit_returns_content(git_repo):
    commits = git_repo.get_file_commits("hello.py")
    # First commit: only one line
    content = git_repo.get_file_at_commit("hello.py", commits[0].hexsha)
    assert "print('hello')" in content
    assert "world" not in content


def test_get_file_at_commit_later_version(git_repo):
    commits = git_repo.get_file_commits("hello.py")
    # Second commit: two lines
    content = git_repo.get_file_at_commit("hello.py", commits[1].hexsha)
    assert "print('hello')" in content
    assert "print('world')" in content


def test_get_file_at_commit_nonexistent_file(git_repo):
    commits = git_repo.get_all_commits()
    result = git_repo.get_file_at_commit("nonexistent.py", commits[0].hexsha)
    assert result == ""


def test_get_commit_files_returns_files_with_stats(git_repo):
    commits = git_repo.get_all_commits()
    # The latest commit modifies src/app.py and hello.py
    files = git_repo.get_commit_files(commits[0].hexsha)
    paths = [f[0] for f in files]
    assert "hello.py" in paths
    assert "src/app.py" in paths
    # Each entry is (path, additions, deletions)
    for path, adds, dels in files:
        assert isinstance(adds, int)
        assert isinstance(dels, int)


def test_get_commit_files_single_file_commit(git_repo):
    # "Add README" commit only touches README.md
    commits = git_repo.get_all_commits()
    readme_commit = [c for c in commits if c.first_line == "Add README"][0]
    files = git_repo.get_commit_files(readme_commit.hexsha)
    assert len(files) == 1
    assert files[0][0] == "README.md"


def test_get_tracked_files_sorted(git_repo):
    files = git_repo.get_tracked_files()
    assert files == sorted(files)
    assert "hello.py" in files
    assert "README.md" in files
    assert "src/app.py" in files


def test_get_tracked_files_excludes_untracked(git_repo):
    files = git_repo.get_tracked_files()
    assert "untracked.txt" not in files


def test_get_untracked_files(git_repo):
    untracked = git_repo.get_untracked_files()
    assert "untracked.txt" in untracked


def test_get_untracked_files_excludes_tracked(git_repo):
    untracked = git_repo.get_untracked_files()
    assert "hello.py" not in untracked


def test_get_file_content_reads_working_tree(git_repo, fixture_repo):
    content = git_repo.get_file_content("hello.py")
    assert "print('hello')" in content
    assert "print('done')" in content


def test_get_file_content_nonexistent(git_repo):
    content = git_repo.get_file_content("does_not_exist.py")
    assert content == ""


def test_has_uncommitted_changes_false(git_repo):
    assert git_repo.has_uncommitted_changes("hello.py") is False


def test_has_uncommitted_changes_true(git_repo, fixture_repo):
    # Make an uncommitted change
    hello_path = os.path.join(fixture_repo, "hello.py")
    with open(hello_path, "a") as f:
        f.write("# uncommitted\n")
    assert git_repo.has_uncommitted_changes("hello.py") is True


def test_get_working_tree_stats_no_changes(git_repo):
    adds, dels = git_repo.get_working_tree_stats("hello.py")
    assert adds == 0
    assert dels == 0


def test_get_working_tree_stats_with_changes(git_repo, fixture_repo):
    hello_path = os.path.join(fixture_repo, "hello.py")
    with open(hello_path, "a") as f:
        f.write("# new line\n# another\n")
    adds, dels = git_repo.get_working_tree_stats("hello.py")
    assert adds == 2
    assert dels == 0


def test_get_diff_to_working_tree(git_repo, fixture_repo):
    hello_path = os.path.join(fixture_repo, "hello.py")
    with open(hello_path, "a") as f:
        f.write("# wip change\n")
    commits = git_repo.get_file_commits("hello.py")
    diff = git_repo.get_diff_to_working_tree("hello.py", commits[-1].hexsha)
    assert "# wip change" in diff


def test_get_diff_to_working_tree_no_changes(git_repo):
    commits = git_repo.get_file_commits("hello.py")
    diff = git_repo.get_diff_to_working_tree("hello.py", commits[-1].hexsha)
    assert diff.strip() == ""


def test_get_blame_returns_tuples(git_repo):
    commits = git_repo.get_file_commits("hello.py")
    blame = git_repo.get_blame("hello.py", commits[-1].hexsha)
    assert len(blame) > 0
    for entry in blame:
        assert len(entry) == 3
        short_hash, author, date = entry
        assert len(short_hash) == 7
        assert isinstance(author, str)
        assert isinstance(date, str)


def test_get_blame_line_count_matches_file(git_repo):
    commits = git_repo.get_file_commits("hello.py")
    blame = git_repo.get_blame("hello.py", commits[-1].hexsha)
    content = git_repo.get_file_at_commit("hello.py", commits[-1].hexsha)
    # blame should have one entry per non-empty line
    file_lines = [l for l in content.split("\n") if l]
    assert len(blame) == len(file_lines)


def test_get_blame_contains_known_author(git_repo):
    commits = git_repo.get_file_commits("hello.py")
    blame = git_repo.get_blame("hello.py", commits[-1].hexsha)
    authors = {entry[1] for entry in blame}
    # The last commit was by "Other Dev", who added the "done" line
    assert "Other Dev" in authors


def test_get_file_contributors_groups_by_email(git_repo):
    contributors = git_repo.get_file_contributors("hello.py")
    assert len(contributors) >= 2
    names = [name for name, count in contributors]
    assert "Test User" in names
    assert "Other Dev" in names


def test_get_file_contributors_sorted_by_count(git_repo):
    contributors = git_repo.get_file_contributors("hello.py")
    counts = [count for _, count in contributors]
    assert counts == sorted(counts, reverse=True)


def test_get_file_contributors_keeps_longer_name(fixture_repo):
    """When same email has multiple names, keep the longer one."""
    repo_dir = fixture_repo
    from git import Repo
    repo = Repo(repo_dir)

    # Add a commit with a short name but same email
    repo.config_writer().set_value("user", "name", "T").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()
    hello_path = os.path.join(repo_dir, "hello.py")
    with open(hello_path, "a") as f:
        f.write("# short name commit\n")
    repo.index.add(["hello.py"])
    repo.index.commit("Short name commit")

    git_repo = GitRepo(repo_dir)
    contributors = git_repo.get_file_contributors("hello.py")
    # "Test User" (longer) should be kept over "T"
    test_email_entries = [name for name, _ in contributors if name in ("Test User", "T")]
    assert "Test User" in test_email_entries
    assert "T" not in test_email_entries


def test_get_branches_returns_current(git_repo):
    branches, current = git_repo.get_branches()
    assert isinstance(branches, list)
    assert isinstance(current, str)
    assert current in branches


def test_get_branches_after_new_branch(fixture_repo):
    from git import Repo
    repo = Repo(fixture_repo)
    repo.create_head("feature-branch")
    git_repo = GitRepo(fixture_repo)
    branches, current = git_repo.get_branches()
    assert "feature-branch" in branches


def test_get_file_commits_oldest_first(git_repo):
    commits = git_repo.get_file_commits("hello.py")
    assert commits[0].first_line == "Initial commit"
    assert commits[-1].first_line == "Update app and hello"


def test_get_file_commits_stats(git_repo):
    commits = git_repo.get_file_commits("hello.py")
    # Second commit adds one line ("world")
    add_world = commits[1]
    assert add_world.first_line == "Add world line"
    assert add_world.additions >= 1


def test_get_all_commits_max_count(git_repo):
    commits = git_repo.get_all_commits(max_count=2)
    assert len(commits) == 2
