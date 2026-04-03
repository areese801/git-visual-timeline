"""Git repository wrapper for gvt."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from git import Repo


@dataclass
class CommitInfo:
    """Represents a single commit's metadata."""

    hexsha: str
    date: datetime
    author: str
    message: str
    additions: int
    deletions: int
    is_wip: bool = False
    refs: str = ""  # branch/tag names associated with this commit

    @property
    def short_hash(self) -> str:
        if self.is_wip:
            return "WIP"
        return self.hexsha[:7]

    @property
    def first_line(self) -> str:
        return self.message.split("\n", 1)[0]

    @property
    def extra_lines(self) -> int:
        lines = self.message.strip().split("\n")
        return max(0, len(lines) - 1)

    @property
    def total_changes(self) -> int:
        return self.additions + self.deletions

    @property
    def searchable_text(self) -> str:
        """Combined text for fuzzy search: message + refs + author."""
        return f"{self.message} {self.refs} {self.author}"


class GitRepo:
    """Wraps gitpython to provide gvt-specific operations."""

    def __init__(self, path: str):
        self.repo = Repo(path, search_parent_directories=True)
        self.root = self.repo.working_tree_dir

    def get_file_commits(self, path: str) -> list[CommitInfo]:
        """
        Get all commits that touched a file, ordered oldest-first.
        Uses git log directly to avoid gitpython object parsing bugs.
        """
        rel_path = self._to_relative(path)

        # Build ref map
        ref_map: dict[str, list[str]] = {}
        try:
            for ref in self.repo.refs:
                try:
                    sha = ref.commit.hexsha
                    ref_map.setdefault(sha, []).append(ref.name)
                except Exception:
                    pass
        except Exception:
            pass

        # Use git log with --numstat for stats, avoiding gitpython's object parser
        output = self.repo.git.log(
            "--format=---GVT_START---%n%H%n%at%n%an%n%s",
            "--numstat",
            "--follow",
            "--", rel_path,
        )

        if not output:
            return []

        commits = []
        chunks = output.split("---GVT_START---")

        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue

            lines = chunk.split("\n")
            if len(lines) < 4:
                continue

            hexsha = lines[0].strip()
            if not hexsha or len(hexsha) != 40:
                continue

            try:
                timestamp = int(lines[1].strip())
            except (ValueError, IndexError):
                continue

            author = lines[2].strip()
            subject = lines[3].strip()

            # Remaining lines are numstat (tab-separated: adds, dels, filename)
            additions = 0
            deletions = 0
            for ns_line in [l.strip() for l in lines[4:] if l.strip()]:
                parts = ns_line.split("\t")
                if len(parts) >= 3:
                    fname = parts[2]
                    if fname == rel_path or fname.endswith("/" + os.path.basename(rel_path)):
                        try:
                            additions = int(parts[0]) if parts[0] != "-" else 0
                            deletions = int(parts[1]) if parts[1] != "-" else 0
                        except ValueError:
                            pass
                        break

            refs_list = ref_map.get(hexsha, [])
            commits.append(
                CommitInfo(
                    hexsha=hexsha,
                    date=datetime.fromtimestamp(timestamp, tz=timezone.utc),
                    author=author,
                    message=subject,
                    additions=additions,
                    deletions=deletions,
                    refs=" ".join(refs_list),
                )
            )

        # Return oldest-first for timeline display
        commits.reverse()
        return commits

    def get_all_commits(self, max_count: int = 500) -> list[CommitInfo]:
        """
        Get recent commits across the entire repo (not file-specific).
        Uses git log directly. Returns newest-first for search display.
        """
        ref_map: dict[str, list[str]] = {}
        try:
            for ref in self.repo.refs:
                try:
                    sha = ref.commit.hexsha
                    ref_map.setdefault(sha, []).append(ref.name)
                except Exception:
                    pass
        except Exception:
            pass

        output = self.repo.git.log(
            f"--max-count={max_count}",
            "--format=---GVT_START---%n%H%n%at%n%an%n%s",
            "--shortstat",
        )

        if not output:
            return []

        commits = []
        chunks = output.split("---GVT_START---")

        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue

            lines = chunk.split("\n")
            if len(lines) < 4:
                continue

            hexsha = lines[0].strip()
            if not hexsha or len(hexsha) != 40:
                continue

            try:
                timestamp = int(lines[1].strip())
            except (ValueError, IndexError):
                continue

            author = lines[2].strip()
            subject = lines[3].strip()

            # Parse shortstat line (e.g. " 3 files changed, 10 insertions(+), 5 deletions(-)")
            total_adds = 0
            total_dels = 0
            for line in lines[4:]:
                if "insertion" in line or "deletion" in line:
                    import re
                    add_match = re.search(r"(\d+) insertion", line)
                    del_match = re.search(r"(\d+) deletion", line)
                    if add_match:
                        total_adds = int(add_match.group(1))
                    if del_match:
                        total_dels = int(del_match.group(1))

            refs_list = ref_map.get(hexsha, [])
            commits.append(
                CommitInfo(
                    hexsha=hexsha,
                    date=datetime.fromtimestamp(timestamp, tz=timezone.utc),
                    author=author,
                    message=subject,
                    additions=total_adds,
                    deletions=total_dels,
                    refs=" ".join(refs_list),
                )
            )
        return commits

    def get_diff(self, path: str, commit_a: str, commit_b: str, context_lines: int = 3) -> str:
        """
        Get unified diff for a file between two commits.
        """
        rel_path = self._to_relative(path)
        # Use git diff directly for context line control
        diff_output = self.repo.git.diff(
            f"-U{context_lines}", commit_a, commit_b, "--", rel_path
        )
        return diff_output

    def has_uncommitted_changes(self, path: str) -> bool:
        """Check if a file has uncommitted changes (staged or unstaged)."""
        rel_path = self._to_relative(path)
        # Check both staged and unstaged
        diff_output = self.repo.git.diff("HEAD", "--", rel_path)
        return bool(diff_output.strip())

    def get_diff_to_working_tree(self, path: str, commit_sha: str, context_lines: int = 3) -> str:
        """Get diff from a commit to the current working tree for a file."""
        rel_path = self._to_relative(path)
        return self.repo.git.diff(f"-U{context_lines}", commit_sha, "--", rel_path)

    def get_working_tree_stats(self, path: str) -> tuple[int, int]:
        """Get +/- stats for uncommitted changes to a file."""
        rel_path = self._to_relative(path)
        output = self.repo.git.diff("--numstat", "HEAD", "--", rel_path)
        if not output.strip():
            return (0, 0)
        parts = output.strip().split("\t")
        try:
            return (int(parts[0]), int(parts[1]))
        except (IndexError, ValueError):
            return (0, 0)

    def get_file_at_commit(self, path: str, commit_sha: str) -> str:
        """
        Get the full file content at a specific commit.
        Uses git show directly to avoid gitpython tree parsing issues.
        """
        rel_path = self._to_relative(path)
        try:
            return self.repo.git.show(f"{commit_sha}:{rel_path}")
        except Exception:
            return ""

    def get_blame(self, path: str, commit_sha: str) -> list[tuple[str, str, str]]:
        """
        Get blame for a file at a commit.
        Returns list of (short_hash, author, date) per line.
        """
        rel_path = self._to_relative(path)
        try:
            output = self.repo.git.blame(
                commit_sha, "--", rel_path,
                porcelain=True,
            )
        except Exception:
            return []

        lines: list[tuple[str, str, str]] = []
        current_hash = ""
        authors: dict[str, str] = {}
        dates: dict[str, str] = {}

        for raw_line in output.split("\n"):
            if raw_line.startswith("\t"):
                # Content line — emit a blame entry
                lines.append((
                    current_hash[:7],
                    authors.get(current_hash, ""),
                    dates.get(current_hash, ""),
                ))
            elif raw_line.startswith("author "):
                authors[current_hash] = raw_line[7:]
            elif raw_line.startswith("author-time "):
                from datetime import datetime, timezone
                ts = int(raw_line[12:])
                dates[current_hash] = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            elif not raw_line.startswith("author-") and not raw_line.startswith("committer") and not raw_line.startswith("summary ") and not raw_line.startswith("previous ") and not raw_line.startswith("filename ") and not raw_line.startswith("boundary"):
                # Could be a commit line: hash orig_line final_line [num_lines]
                parts = raw_line.split()
                if parts and len(parts[0]) == 40:
                    current_hash = parts[0]

        return lines

    def get_file_contributors(self, path: str) -> list[tuple[str, int]]:
        """
        Get all contributors to a file with commit counts, sorted by most commits.
        Groups by email so different names with the same email are unified.
        Returns list of (author_name, commit_count).
        """
        rel_path = self._to_relative(path)
        output = self.repo.git.log(
            "--format=%ae%n%an",
            "--follow",
            "--", rel_path,
        )
        if not output:
            return []

        lines = output.strip().split("\n")
        by_email: dict[str, tuple[str, int]] = {}
        # Lines come in pairs: email, then name
        for i in range(0, len(lines) - 1, 2):
            email = lines[i].strip()
            name = lines[i + 1].strip()
            if not email:
                continue
            if email in by_email:
                prev_name, prev_count = by_email[email]
                best_name = name if len(name) > len(prev_name) else prev_name
                by_email[email] = (best_name, prev_count + 1)
            else:
                by_email[email] = (name, 1)

        result = [(name, count) for name, count in by_email.values()]
        return sorted(result, key=lambda x: x[1], reverse=True)

    def get_commit_files(self, commit_sha: str) -> list[tuple[str, int, int]]:
        """
        Get all files changed in a commit with their stats.
        Returns list of (file_path, additions, deletions).
        """
        commit = self.repo.commit(commit_sha)
        files = []
        try:
            for file_path, stats in commit.stats.files.items():
                files.append((
                    file_path,
                    stats.get("insertions", 0),
                    stats.get("deletions", 0),
                ))
        except Exception:
            pass
        return sorted(files, key=lambda x: x[0])

    def get_tracked_files(self) -> list[str]:
        """
        Get all tracked file paths relative to repo root.
        Uses git ls-tree directly to avoid gitpython tree parsing issues.
        """
        output = self.repo.git.ls_tree("-r", "--name-only", "HEAD")
        if not output:
            return []
        return sorted(output.split("\n"))

    def get_untracked_files(self) -> list[str]:
        """
        Get all untracked file paths relative to repo root.
        """
        output = self.repo.git.ls_files("--others", "--exclude-standard")
        if not output:
            return []
        return sorted(output.split("\n"))

    def get_file_content(self, path: str) -> str:
        """
        Get the current working tree content of a file.
        """
        rel_path = self._to_relative(path)
        full_path = os.path.join(self.root, rel_path)
        try:
            with open(full_path, "r", errors="replace") as f:
                return f.read()
        except (OSError, UnicodeDecodeError):
            return ""

    def get_branches(self) -> tuple[list[str], str]:
        """
        Get list of branch names and the current branch name.
        """
        branches = [b.name for b in self.repo.branches]
        try:
            current = self.repo.active_branch.name
        except TypeError:
            current = "HEAD"
        return branches, current

    def _to_relative(self, path: str) -> str:
        """Convert a path to be relative to the repo root."""
        if os.path.isabs(path):
            return os.path.relpath(path, self.root)
        return path
