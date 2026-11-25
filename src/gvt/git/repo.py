"""Git repository wrapper for gvt."""

from __future__ import annotations

import hashlib
import os
import re
import threading
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from git import Repo
from git.exc import GitCommandError

from gvt.logging_setup import get_logger
from gvt.textsafe import safe_name, safe_text

log = get_logger(__name__)

# Commit records start with a NUL byte, which can't appear in commit metadata
LOG_FORMAT = "--format=%x00%H%n%at%n%an%n%B"
RECORD_SEPARATOR = "\x00"
OBJECT_ID = re.compile(r"(?:[a-f0-9]{40}|[a-f0-9]{64})")

# Never run diff programs or text converters configured by the repo
SAFE_DIFF = ("--no-ext-diff", "--no-textconv")

# Largest working-tree file shown as a preview
MAX_PREVIEW_BYTES = 2_000_000

# Commit timestamps are clamped to 1970..2100: a crafted date outside Python's
# datetime range would otherwise crash parsing
MAX_TIMESTAMP = 4_102_444_800  # 2100-01-01 UTC


def commit_date(timestamp: int) -> datetime:
    """
    UTC datetime for a git timestamp, clamped to 1970-01-01..2100-01-01.
    """
    return datetime.fromtimestamp(max(0, min(timestamp, MAX_TIMESTAMP)), tz=timezone.utc)


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
    # (path, additions, deletions) per file; filled by get_scope_commits
    files: list[tuple[str, int, int]] = field(default_factory=list)

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


@dataclass
class TagInfo:
    """
    A tag name and the commit it points at.
    """

    name: str
    hexsha: str
    date: datetime


def _numstat_entry(record: str, fields: Iterator[str]) -> tuple[str, int, int]:
    """
    Read one Git --numstat -z entry, including the two names of a rename.
    """
    adds, dels, path = record.split("\t", 2)
    if not path:
        next(fields)  # source of a rename or copy
        path = next(fields)
    return path, 0 if adds == "-" else int(adds), 0 if dels == "-" else int(dels)


# Max number of scoped logs kept in memory
SCOPE_CACHE_SIZE = 8


class GitRepo:
    """Wraps gitpython to provide gvt-specific operations."""

    def __init__(self, path: str):
        self.repo = Repo(path, search_parent_directories=True)
        self.root = self.repo.working_tree_dir
        self._scope_cache: OrderedDict[tuple[str, str], list[CommitInfo]] = OrderedDict()
        # Scoped logs are read from worker threads
        self._scope_cache_lock = threading.Lock()
        # Paths are file names, not pathspecs: "app/[slug]/page.tsx" must not
        # match "app/s/page.tsx". List non-ASCII paths as-is instead of
        # C-quoting them, and never run a repo-configured fsmonitor hook.
        self.repo.git.update_environment(GIT_LITERAL_PATHSPECS="1")
        self.repo.git.set_persistent_git_options(
            c=["core.quotePath=false", "core.fsmonitor=false"]
        )

    def _build_ref_map(self) -> dict[str, list[str]]:
        """Build a sha -> [ref names] map, tolerating individual bad refs."""
        ref_map: dict[str, list[str]] = {}
        try:
            refs = list(self.repo.refs)
        except (GitCommandError, AttributeError, ValueError) as e:
            log.warning("failed to list refs: %s", e)
            return ref_map
        for ref in refs:
            try:
                sha = ref.commit.hexsha
                # Ref names may hold bidi or C1 characters; they're only displayed
                ref_map.setdefault(sha, []).append(safe_text(ref.name))
            except (GitCommandError, AttributeError, ValueError) as e:
                log.debug("skipping ref %s: %s", getattr(ref, "name", "?"), e)
        return ref_map

    def get_file_commits(self, path: str) -> list[CommitInfo]:
        """
        Get all commits that touched a file, ordered oldest-first.
        Uses git log directly to avoid gitpython object parsing bugs.
        """
        rel_path = self._to_relative(path)

        if self.get_head_sha() is None:
            return []
        output = self.repo.git.log(
            *SAFE_DIFF, "-z", LOG_FORMAT, "--numstat", "--follow", "--", rel_path
        )
        return list(reversed(self._parse_log(output, self._build_ref_map())))

    def get_all_commits(self, max_count: int = 500) -> list[CommitInfo]:
        """
        Get recent commits across the entire repo (not file-specific).
        Uses git log directly. Returns newest-first for search display.
        """
        if self.get_head_sha() is None:
            return []
        ref_map = self._build_ref_map()

        output = self.repo.git.log(
            *SAFE_DIFF, "-z",
            f"--max-count={max_count}",
            "--no-merges",
            LOG_FORMAT,
            "--shortstat",
        )
        return self._parse_log(output, ref_map)

    def get_scope_commits(self, path: str) -> list[CommitInfo]:
        """
        Get all non-merge commits touching a file or directory, newest-first.

        Each commit carries per-file line counts (CommitInfo.files), limited to
        the scope by the pathspec, so a directory's additions/deletions only
        count its own files. Binary files count as 0 lines. Results are cached per
        (scope, HEAD) so a new commit invalidates them.

        :param path: File or directory path, relative or absolute. "" or "." means
            the whole repo.
        :returns: Commits newest-first; empty for an empty repo or unknown path.
        :raises GitCommandError: If git log fails for a reason other than an
            empty repo.
        """
        scope = self._normalize_scope(path)
        head = self.get_head_sha()
        if head is None:
            return []

        key = (scope, head)
        with self._scope_cache_lock:
            cached = self._scope_cache.get(key)
            if cached is not None:
                self._scope_cache.move_to_end(key)
                return cached

        # --follow only works for one file; it keeps history from before a rename
        entry = self.repo.git.ls_tree("-z", head, "--", scope) if scope != "." else ""
        follow = ("--follow",) if entry.split(" ", 2)[1:2] == ["blob"] else ()
        output = self.repo.git.log(
            *SAFE_DIFF,
            "-z",
            "--no-merges",
            *follow,
            LOG_FORMAT,
            "--numstat",
            head,
            "--",
            scope,
        )
        commits = self._parse_log(output, self._build_ref_map())

        with self._scope_cache_lock:
            self._scope_cache[key] = commits
            while len(self._scope_cache) > SCOPE_CACHE_SIZE:
                self._scope_cache.popitem(last=False)
        return commits

    def get_head_sha(self) -> str | None:
        """
        Return the HEAD commit sha, or None when the repo has no commits.
        """
        try:
            return self.repo.git.rev_parse("--verify", "--quiet", "HEAD").strip() or None
        except GitCommandError:
            return None

    def get_first_commit_date(self) -> datetime | None:
        """
        Date of the repo's oldest root commit, or None when there are no commits.
        """
        try:
            output = self.repo.git.log("--max-parents=0", "--format=%at", "HEAD")
        except GitCommandError:
            return None
        stamps = [int(line) for line in output.split() if line.isdigit()]
        return commit_date(min(stamps)) if stamps else None

    def get_tags(self) -> list[TagInfo]:
        """
        List tags with the date of the commit each one points at, oldest-first.
        """
        try:
            output = self.repo.git.log("--no-walk", "--tags", "--format=%H%x09%at%x09%D")
        except GitCommandError as e:
            log.warning("failed to list tags: %s", e)
            return []

        tags = []
        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            hexsha, timestamp, decorations = parts
            try:
                date = commit_date(int(timestamp))
            except ValueError:
                continue
            for deco in decorations.split(", "):
                if deco.startswith("tag: "):
                    # Tag names are only displayed; they may hold bidi or C1 characters
                    tags.append(TagInfo(name=safe_text(deco[len("tag: "):]), hexsha=hexsha, date=date))

        tags.sort(key=lambda t: (t.date, t.name))
        return tags

    def _normalize_scope(self, path: str) -> str:
        """
        Turn a scope path into a repo-relative pathspec ("." for the whole repo).
        """
        rel = self._to_relative(path).strip("/") if path else ""
        return rel if rel and rel != "." else "."

    @staticmethod
    def _parse_log(output: str, ref_map: dict[str, list[str]]) -> list[CommitInfo]:
        """
        Parse NUL-framed headers and Git's shortstat or machine-readable numstat.
        """
        commits: list[CommitInfo] = []
        fields = iter(output.split(RECORD_SEPARATOR))
        commit = None
        for record in fields:
            if not record:
                continue
            sha, sep, header = record.partition("\n")
            if sep and OBJECT_ID.fullmatch(sha):
                try:
                    timestamp, author, message = header.split("\n", 2)
                    date = commit_date(int(timestamp))
                except ValueError:
                    commit = None
                    continue
                commit = CommitInfo(
                    hexsha=sha,
                    date=date,
                    author=safe_text(author),
                    message=safe_text(message.rstrip("\n")),
                    additions=0,
                    deletions=0,
                    refs=" ".join(ref_map.get(sha, [])),
                )
                commits.append(commit)
                continue
            stat = record.lstrip("\n")
            if "\t" in stat:
                path, adds, dels = _numstat_entry(stat, fields)
                if commit is None:
                    continue
                commit.files.append((path, adds, dels))
                commit.additions += adds
                commit.deletions += dels
            elif commit is not None:
                for amount, kind in re.findall(r"(\d+) (insertion|deletion)", stat):
                    if kind == "insertion":
                        commit.additions = int(amount)
                    else:
                        commit.deletions = int(amount)
        return commits

    def get_diff(
        self,
        path: str,
        commit_a: str,
        commit_b: str,
        context_lines: int = 3,
        *,
        previous_path: str | None = None,
    ) -> str:
        """
        Get unified diff for a file between two commits.
        """
        path = self._to_relative(path)
        if previous_path and previous_path != path:
            return self._renamed_diff(
                self._to_relative(previous_path),
                path,
                commit_a,
                commit_b,
                context_lines,
            )
        return safe_text(
            self.repo.git.diff(
                *SAFE_DIFF, f"-U{context_lines}", commit_a, commit_b, "--", path
            )
        )

    def _renamed_diff(
        self, old: str, new: str, left: str, right: str | None, context: int
    ) -> str:
        git = self.repo.git
        options = (*SAFE_DIFF, f"-U{context}")
        old_exists = bool(git.ls_tree("-z", left, "--", old))
        if right is None:
            work_path = os.path.join(self.root, new)
            new_exists = os.path.islink(work_path) or os.path.isfile(work_path)
        else:
            new_exists = bool(git.ls_tree("-z", right, "--", new))
        if old_exists and new_exists:
            args = (f"{right}:{new}", "--") if right is not None else ("--", new)
            patch = git.diff(*options, f"{left}:{old}", *args)
            return (
                safe_text(patch)
                if patch
                else f"rename from {safe_name(old)}\nrename to {safe_name(new)}"
            )
        # Git recognizes its empty tree without creating an object in the repository.
        algorithm = "sha256" if len(left) == 64 else "sha1"
        empty = hashlib.new(algorithm, b"tree 0\0").hexdigest()
        if old_exists:
            return safe_text(git.diff(*options, left, empty, "--", old))
        if new_exists:
            endpoint = (right,) if right is not None else ()
            return safe_text(git.diff(*options, empty, *endpoint, "--", new))
        return ""

    def has_uncommitted_changes(self, path: str) -> bool:
        """Check if a file has uncommitted changes (staged or unstaged)."""
        rel_path = self._to_relative(path)
        # Check both staged and unstaged
        diff_output = self.repo.git.diff(*SAFE_DIFF, "HEAD", "--", rel_path)
        return bool(diff_output.strip())

    def get_diff_to_working_tree(
        self,
        path: str,
        commit_sha: str,
        context_lines: int = 3,
        *,
        previous_path: str | None = None,
    ) -> str:
        """Get diff from a commit to the current working tree for a file."""
        path = self._to_relative(path)
        if previous_path and previous_path != path:
            return self._renamed_diff(
                self._to_relative(previous_path), path, commit_sha, None, context_lines
            )
        return safe_text(
            self.repo.git.diff(*SAFE_DIFF, f"-U{context_lines}", commit_sha, "--", path)
        )

    def get_working_tree_stats(self, path: str) -> tuple[int, int]:
        """Get +/- stats for uncommitted changes to a file."""
        rel_path = self._to_relative(path)
        output = self.repo.git.diff(*SAFE_DIFF, "--numstat", "HEAD", "--", rel_path)
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
            return safe_text(self.repo.git.show(f"{commit_sha}:{rel_path}"))
        except GitCommandError as e:
            log.warning("git show %s:%s failed: %s", commit_sha, rel_path, e)
            return ""

    def get_blame(self, path: str, commit_sha: str) -> list[tuple[str, str, str]]:
        """
        Get blame for a file at a commit.
        Returns list of (short_hash, author, date) per line.
        """
        rel_path = self._to_relative(path)
        try:
            output = self.repo.git.blame(
                "--no-textconv", commit_sha, "--", rel_path,
                porcelain=True,
            )
        except GitCommandError as e:
            log.warning("git blame %s -- %s failed: %s", commit_sha, rel_path, e)
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
                authors[current_hash] = safe_text(raw_line[7:])
            elif raw_line.startswith("author-time "):
                ts = int(raw_line[12:])
                dates[current_hash] = commit_date(ts).astimezone().strftime("%Y-%m-%d")
            elif not raw_line.startswith("author-") and not raw_line.startswith("committer") and not raw_line.startswith("summary ") and not raw_line.startswith("previous ") and not raw_line.startswith("filename ") and not raw_line.startswith("boundary"):
                # Could be a commit line: hash orig_line final_line [num_lines]
                parts = raw_line.split()
                if parts and OBJECT_ID.fullmatch(parts[0]):
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
            name = safe_text(lines[i + 1].strip())
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

        Uses git diff-tree directly to avoid gitpython's commit.stats
        which can fail with ValueError on repos with dubious ownership
        or other gitpython object-traversal bugs.
        """
        try:
            output = self.repo.git.diff_tree(
                *SAFE_DIFF, "--numstat", "-z", "-r", "--root", "--no-commit-id", commit_sha
            )
        except (GitCommandError, ValueError) as e:
            log.warning("diff-tree for %s failed: %s", commit_sha, e)
            return []

        if not output:
            return []

        records = iter(output.split("\0"))
        return sorted(_numstat_entry(record, records) for record in records if record)

    def get_tracked_files(self) -> list[str]:
        """
        Get all tracked file paths relative to repo root.
        Uses git ls-tree directly to avoid gitpython tree parsing issues.
        """
        if self.get_head_sha() is None:
            output = self.repo.git.ls_files("-z", "--cached")
        else:
            output = self.repo.git.ls_tree("-rz", "--name-only", "HEAD")
        if not output:
            return []
        return sorted(output.removesuffix("\0").split("\0"))

    def get_untracked_files(self) -> list[str]:
        """
        Get all untracked file paths relative to repo root.
        """
        output = self.repo.git.ls_files("-z", "--others", "--exclude-standard")
        if not output:
            return []
        return sorted(output.removesuffix("\0").split("\0"))

    def get_file_content(self, path: str) -> str:
        """
        Get the current working tree content of a file.

        Only regular files inside the repo are read (a symlink pointing
        elsewhere, a FIFO or a device returns ""), and only the first
        MAX_PREVIEW_BYTES.
        """
        rel_path = self._to_relative(path)
        full_path = os.path.join(self.root, rel_path)
        real_root = os.path.realpath(self.root)
        real_path = os.path.realpath(full_path)
        if os.path.commonpath([real_root, real_path]) != real_root or not os.path.isfile(real_path):
            log.info("not previewing %s: outside the repo or not a regular file", rel_path)
            return ""
        try:
            with open(real_path, "r", errors="replace") as f:
                return safe_text(f.read(MAX_PREVIEW_BYTES))
        except (OSError, UnicodeDecodeError):
            return ""

    def get_branches(self) -> tuple[list[str], str]:
        """
        Get list of branch names and the current branch name.
        """
        branches = [b.name for b in self.repo.branches]
        return branches, self.get_current_branch()

    def get_current_branch(self) -> str:
        """
        Return the active branch name, or HEAD when detached.
        """
        try:
            return self.repo.active_branch.name
        except TypeError:
            # Detached HEAD — expected when viewing a specific commit.
            log.debug("detached HEAD; active_branch unavailable")
            return "HEAD"

    def _to_relative(self, path: str) -> str:
        """Convert a path to be relative to the repo root."""
        if os.path.isabs(path):
            return os.path.relpath(path, self.root)
        return path
