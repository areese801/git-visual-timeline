"""
Exclusion rules for the Evolution views: which tracked files count as authored.

Lockfiles, generated snapshots, minified bundles and vendored code are committed
on purpose but say little about how a project evolves, so the Evolution views
can leave them out ("authored" mode). Rules come from layers, applied in order
with the last matching rule winning and a leading "!" re-including a path:

1. Built-in presets (DEFAULT_PRESETS on unless configured otherwise)
2. .gitattributes linguist-generated / -vendored / -documentation
3. User config: ~/.config/gvt/config.toml ($GVT_CONFIG overrides the path)
4. Repo config: .gvt.toml at the repo root

Patterns are gitignore-style globs; "re:" marks a regular expression. Config
files may also list ignore files (e.g. a .clocignore of regexes) and an
ignore-revs file of commits to drop entirely (formatting passes).
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from gvt.git.repo import CommitInfo
from gvt.textsafe import safe_text

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

PRESETS: dict[str, list[str]] = {
    "lockfiles": [
        "pnpm-lock.yaml", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
        "bun.lock", "bun.lockb", "uv.lock", "poetry.lock", "pdm.lock", "Pipfile.lock",
        "Cargo.lock", "Gemfile.lock", "composer.lock", "mix.lock", "flake.lock", "go.sum",
    ],
    "minified": ["*.min.js", "*.min.css", "*.map"],
    "generated": [
        "*.snap", "*.tsbuildinfo", "**/migrations/meta/*_snapshot.json", "**/alembic/versions/",
    ],
    "vendored": ["vendor/", "third_party/"],
    "docs": ["docs/", "*.md", "*.rst"],
    "data": ["*.json", "*.csv", "*.svg"],
}

DEFAULT_PRESETS = ("lockfiles", "minified", "generated", "vendored")

REPO_CONFIG_NAME = ".gvt.toml"
DEFAULT_IGNORE_REVS = ".git-blame-ignore-revs"

LINGUIST_ATTRIBUTES = ("linguist-generated", "linguist-vendored", "linguist-documentation")

# Limits that keep rules from an untrusted repo cheap to load and match
MAX_PATTERN_LENGTH = 256
MAX_MATCH_PATH = 1024  # longer paths are never matched (treated as kept)
MAX_RULE_FILE_BYTES = 256_000


def user_config_path() -> Path:
    """
    The user config file: $GVT_CONFIG if set, else ~/.config/gvt/config.toml.
    """
    override = os.environ.get("GVT_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "gvt" / "config.toml"


# Default for `user_config` parameters: resolve user_config_path() at call time
USER_CONFIG = Path("<user config>")


def _label(path: Path) -> str:
    """
    Path for display, with the home directory shortened to ~.
    """
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home):] if text.startswith(home + os.sep) else text


# Path-level token: "**" matches any number of whole path segments
_ANY_SEGMENTS = "**"


def _class_end(segment: str, start: int) -> int:
    """
    Index of the "]" closing a [class] that opens at `start`, or -1.

    A "]" right after "[" or "[!" is a literal member of the class.
    """
    j = start + 1
    if j < len(segment) and segment[j] == "!":
        j += 1
    if j < len(segment) and segment[j] == "]":
        j += 1
    return segment.find("]", j)


def _segment_tokens(segment: str) -> list[tuple[str, object]]:
    """
    Tokenize one path segment of a glob: "*", "?", [classes], literals.
    """
    tokens: list[tuple[str, object]] = []
    i = 0
    while i < len(segment):
        ch = segment[i]
        if ch == "*":
            while i + 1 < len(segment) and segment[i + 1] == "*":
                i += 1  # "**" inside a segment acts like "*"
            tokens.append(("star", None))
        elif ch == "?":
            tokens.append(("any", None))
        elif ch == "[" and _class_end(segment, i) != -1:
            end = _class_end(segment, i)
            body = segment[i + 1:end]
            negate = body.startswith("!")
            if negate:
                body = body[1:]
            chars: set[str] = set()
            j = 0
            while j < len(body):
                if j + 2 < len(body) and body[j + 1] == "-":
                    chars.update(chr(c) for c in range(ord(body[j]), ord(body[j + 2]) + 1))
                    j += 3
                else:
                    chars.add(body[j])
                    j += 1
            tokens.append(("class", (frozenset(chars), negate)))
            i = end
        else:
            tokens.append(("lit", ch))
        i += 1
    return tokens


def _token_matches(token: tuple[str, object], ch: str) -> bool:
    kind, value = token
    if kind == "any":
        return True
    if kind == "lit":
        return ch == value
    chars, negate = value  # class
    return (ch in chars) != negate


def _wildcard_match(tokens: list, items: list, is_star, item_matches) -> bool:
    """
    Linear-time wildcard matching with a single backtrack point.

    `is_star(token)` marks tokens that match any run of items; every other
    token matches exactly one item when `item_matches(token, item)`.
    """
    t = i = 0
    star_t, star_i = -1, 0
    while i < len(items):
        if t < len(tokens) and not is_star(tokens[t]) and item_matches(tokens[t], items[i]):
            t += 1
            i += 1
        elif t < len(tokens) and is_star(tokens[t]):
            star_t, star_i = t, i
            t += 1
        elif star_t != -1:
            t = star_t + 1
            star_i += 1
            i = star_i
        else:
            return False
    while t < len(tokens) and is_star(tokens[t]):
        t += 1
    return t == len(tokens)


class Glob:
    """
    A gitignore-style glob, matched without regular expressions so that no
    pattern can make matching slow.

    A pattern with no "/" (other than a trailing one) matches at any depth; a
    pattern containing "/" is anchored at the repo root. A trailing "/" matches
    only directories (anything beneath them). "*" stays within a path segment,
    "**" crosses segments, "?" and [classes] work as in gitignore. A pattern
    that names a directory also matches everything beneath it.
    """

    def __init__(self, pattern: str) -> None:
        dir_only = pattern.endswith("/")
        body = pattern.rstrip("/")
        anchored = "/" in body
        segments = [seg for seg in body.lstrip("/").split("/") if seg]
        if not anchored:
            segments.insert(0, _ANY_SEGMENTS)
        # A directory-only pattern needs at least one segment beneath it
        segments += ["*", _ANY_SEGMENTS] if dir_only else [_ANY_SEGMENTS]

        tokens: list[object] = []
        for seg in segments:
            if seg == _ANY_SEGMENTS:
                if not tokens or tokens[-1] is not _ANY_SEGMENTS:
                    tokens.append(_ANY_SEGMENTS)  # repeated "**/" collapses
            else:
                tokens.append(_segment_tokens(seg))
        self.tokens = tokens
        self.pattern = pattern

    def match(self, path: str) -> bool:
        return _wildcard_match(
            self.tokens,
            path.split("/"),
            lambda token: token is _ANY_SEGMENTS,
            lambda token, segment: _wildcard_match(
                token, list(segment), lambda t: t[0] == "star", _token_matches
            ),
        )


def compile_glob(pattern: str) -> Glob:
    """
    Compile a gitignore-style glob (see Glob).
    """
    return Glob(pattern)


@dataclass(frozen=True)
class Rule:
    """
    One exclusion pattern and where it came from.
    """

    pattern: str
    source: str
    negate: bool = False
    regex: bool = False
    compiled: re.Pattern[str] | Glob = field(default=re.compile(""), compare=False, hash=False, repr=False)
    # The line as written, for listings
    text: str = field(default="", compare=False)

    def matches(self, path: str) -> bool:
        if self.regex:
            return self.compiled.search(path) is not None
        return self.compiled.match(path)

    @property
    def label(self) -> str:
        """
        "source  pattern" as shown in rule listings.
        """
        text = self.text or self.pattern
        if self.negate and not text.startswith("!"):
            text = "!" + text
        # Patterns come from files in the repo; never print them raw
        return safe_text(f"{self.source}  {text}")


def parse_pattern(text: str, source: str, syntax: str = "glob", allow_regex: bool = True) -> Rule | None:
    """
    Parse one pattern line.

    :param text: Pattern as written: "!" negates, "re:" switches to a regex.
        Blank lines and "#" comments return None.
    :param source: Layer label for listings (e.g. ".gvt.toml").
    :param syntax: Default syntax for the line, "glob" or "regex".
    :param allow_regex: False to read every line as a glob ("re:" is literal).
    :raises ValueError: If the pattern is too long or a regex doesn't compile.
    """
    line = text.strip()
    if not line or line.startswith("#"):
        return None
    if len(line) > MAX_PATTERN_LENGTH:
        raise ValueError(f"pattern in {source} is too long (over {MAX_PATTERN_LENGTH} characters)")
    negate = line.startswith("!")
    if negate:
        line = line[1:]
    regex = allow_regex and syntax == "regex"
    if allow_regex and line.startswith("re:"):
        regex = True
        line = line[3:]
    try:
        compiled = re.compile(line) if regex else compile_glob(line)
    except re.error as e:
        raise ValueError(f"bad pattern {text.strip()!r} in {source}: {e}") from e
    return Rule(
        pattern=line, source=source, negate=negate, regex=regex, compiled=compiled, text=text.strip()
    )


def gitattributes_rules(text: str, warnings: list[str] | None = None) -> list[Rule]:
    """
    Rules from .gitattributes lines that set or unset linguist attributes.

    "linguist-generated" / "=true" excludes; "-linguist-generated" / "=false"
    re-includes. Patterns are always globs, as in git.

    :param warnings: Collects problems with individual lines, if given.
    """
    rules = []
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        pattern, attrs = parts[0], parts[1:]
        verdict = None
        for attr in attrs:
            name, _, value = attr.lstrip("-!").partition("=")
            if name not in LINGUIST_ATTRIBUTES:
                continue
            unset = attr.startswith(("-", "!")) or value.lower() == "false"
            verdict = "include" if unset else "exclude"
        if verdict:
            try:
                rule = parse_pattern(pattern, ".gitattributes", allow_regex=False)
            except ValueError as e:
                if warnings is not None:
                    warnings.append(str(e))
                continue
            if rule:
                rules.append(replace(rule, negate=verdict == "include"))
    return rules


@dataclass
class ExclusionConfig:
    """
    Merged settings from the user and repo config files.
    """

    default_mode: str = "authored"
    presets: list[str] = field(default_factory=lambda: list(DEFAULT_PRESETS))
    use_gitattributes: bool = True
    # (pattern, source label) in layer order
    exclude: list[tuple[str, str]] = field(default_factory=list)
    # (path, syntax, source label) in layer order
    ignore_files: list[tuple[str, str, str]] = field(default_factory=list)
    ignore_revs: str = DEFAULT_IGNORE_REVS
    # Which layer set ignore_revs: "default", the user label, or REPO_CONFIG_NAME
    ignore_revs_source: str = "default"
    # Regex rules from files inside the repo are skipped unless the user opts in
    trust_repo_regex: bool = False
    # Label of the user layer (its path, shortened)
    user_label: str = ""
    # Config files that exist, by label
    found: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _inside(root: str, path: Path | str) -> bool:
    """
    True when `path` (after following symlinks) is inside `root`.
    """
    real_root = os.path.realpath(root)
    return os.path.commonpath([real_root, os.path.realpath(path)]) == real_root


def _read_small(path: Path, label: str, config: ExclusionConfig) -> str | None:
    """
    Read a config or rules file, refusing ones over MAX_RULE_FILE_BYTES.
    """
    try:
        if path.stat().st_size > MAX_RULE_FILE_BYTES:
            config.warnings.append(f"{label} is too large to read (over {MAX_RULE_FILE_BYTES // 1000} KB)")
            return None
        return path.read_text()
    except (OSError, UnicodeDecodeError) as e:
        config.warnings.append(f"couldn't read {label}: {e}")
        return None


def _read_layer(path: Path, label: str, config: ExclusionConfig, repo_root: str | None = None) -> None:
    """
    Merge one config file into `config` (scalars override, lists append).

    :param repo_root: Set for the repo layer: the file must stay inside it,
        and settings only a user may grant are ignored.
    """
    if not path.is_file():
        return
    if repo_root is not None and not _inside(repo_root, path):
        config.warnings.append(f"{label} points outside the repo; ignored")
        return
    text = _read_small(path, label, config)
    if text is None:
        return
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        config.warnings.append(f"couldn't read {label}: {e}")
        return
    config.found.append(label)
    section = data.get("evolution", {})

    mode = section.get("default_mode")
    if mode in ("authored", "everything"):
        config.default_mode = mode
    elif mode is not None:
        config.warnings.append(f"{label}: default_mode must be 'authored' or 'everything'")

    if "presets" in section:
        presets = [str(p) for p in section["presets"]]
        for name in presets:
            if name not in PRESETS:
                config.warnings.append(f"{label}: unknown preset '{name}'")
        config.presets = [p for p in presets if p in PRESETS]

    if "use_gitattributes" in section:
        config.use_gitattributes = bool(section["use_gitattributes"])
    if "ignore_revs" in section:
        config.ignore_revs = str(section["ignore_revs"])
        config.ignore_revs_source = label
    if "trust_repo_regex" in section:
        if repo_root is None:
            config.trust_repo_regex = bool(section["trust_repo_regex"])
        else:
            config.warnings.append(
                f"{label}: trust_repo_regex is only read from your own config "
                f"({config.user_label or '~/.config/gvt/config.toml'}); ignored"
            )

    config.exclude += [(str(p), label) for p in section.get("exclude", [])]
    for entry in section.get("ignore_files", []):
        if isinstance(entry, str):
            config.ignore_files.append((entry, "glob", label))
        elif isinstance(entry, dict) and "path" in entry:
            config.ignore_files.append((str(entry["path"]), str(entry.get("syntax", "glob")), label))
        else:
            config.warnings.append(f"{label}: ignore_files entries need a path")


def load_config(repo_root: str, user_config: Path | None = USER_CONFIG) -> ExclusionConfig:
    """
    Merge defaults, the user config, and the repo's .gvt.toml (in that order).

    :param user_config: Path to the user config, None to skip it, or the
        USER_CONFIG default for user_config_path().
    """
    config = ExclusionConfig()
    if user_config is USER_CONFIG:
        user_config = user_config_path()
    if user_config is not None:
        config.user_label = _label(user_config)
        _read_layer(user_config, config.user_label, config)
    _read_layer(Path(repo_root) / REPO_CONFIG_NAME, REPO_CONFIG_NAME, config, repo_root=repo_root)
    return config


def _count(n: int, word: str) -> str:
    """
    "1 rule" / "3 rules".
    """
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _resolve(repo_root: str, path: str) -> Path:
    expanded = Path(os.path.expanduser(path))
    return expanded if expanded.is_absolute() else Path(repo_root) / expanded


@dataclass
class FilterResult:
    """
    Commits after exclusion, plus what was left out.
    """

    commits: list[CommitInfo]
    excluded_lines: int = 0
    dropped_commits: int = 0
    # Lines added + deleted across all input commits
    total_lines: int = 0
    # Rule label -> lines it removed
    by_rule: dict[str, int] = field(default_factory=dict)
    # Rule label -> number of distinct files it matched
    rule_files: dict[str, int] = field(default_factory=dict)
    # Excluded path -> (lines removed, label of the rule that matched it)
    by_file: dict[str, tuple[int, str]] = field(default_factory=dict)
    # Kept path -> lines changed (for spotting noise the rules missed)
    kept_by_file: dict[str, int] = field(default_factory=dict)


@dataclass
class LayerStatus:
    """
    How one rule layer was resolved for a repo, for the details view.
    """

    name: str
    detail: str
    active: bool


class Exclusions:
    """
    Compiled rules for one repo, with path matching and commit filtering.
    """

    def __init__(
        self,
        rules: list[Rule],
        ignore_revs: set[str],
        config: ExclusionConfig,
        layers: list[LayerStatus] | None = None,
    ) -> None:
        self.rules = rules
        self.ignore_revs = ignore_revs
        self.config = config
        # How each layer contributed, in the order rules are applied
        self.layers = layers or []
        self._verdicts: dict[str, Rule | None] = {}

    @classmethod
    def load(cls, repo_root: str, user_config: Path | None = USER_CONFIG) -> Exclusions:
        """
        Build the rules for a repo from presets, .gitattributes, and config files.
        """
        config = load_config(repo_root, user_config)
        rules: list[Rule] = []
        # Regex rules skipped because they come from inside an untrusted repo
        skipped_regex: Counter[str] = Counter()

        def add(text: str, source: str, syntax: str = "glob", from_repo: bool = False) -> None:
            try:
                rule = parse_pattern(text, source, syntax)
            except ValueError as e:
                config.warnings.append(str(e))
                return
            if rule is None:
                return
            if rule.regex and from_repo and not config.trust_repo_regex:
                skipped_regex[source] += 1
                return
            rules.append(rule)

        layers: list[LayerStatus] = []

        for name in config.presets:
            for pattern in PRESETS[name]:
                add(pattern, f"preset:{name}")
        off = [name for name in PRESETS if name not in config.presets]
        layers.append(
            LayerStatus(
                "Built-in presets",
                f"on: {', '.join(config.presets) or 'none'}"
                + (f"  ·  off: {', '.join(off)}" if off else ""),
                bool(config.presets),
            )
        )

        attributes = Path(repo_root) / ".gitattributes"
        if not config.use_gitattributes:
            layers.append(LayerStatus(".gitattributes", "turned off (use_gitattributes = false)", False))
        elif attributes.is_file():
            text = _read_small(attributes, ".gitattributes", config) if _inside(repo_root, attributes) else None
            if text is None:
                if not _inside(repo_root, attributes):
                    config.warnings.append(".gitattributes points outside the repo; ignored")
                layers.append(LayerStatus(".gitattributes", "couldn't be read", False))
            else:
                found = gitattributes_rules(text, config.warnings)
                rules += found
                layers.append(LayerStatus(".gitattributes", _count(len(found), "linguist rule"), bool(found)))
        else:
            layers.append(LayerStatus(".gitattributes", "no file in this repo", False))

        for label in (config.user_label, REPO_CONFIG_NAME):
            if not label:
                continue
            before = len(rules)
            from_repo = label == REPO_CONFIG_NAME
            patterns = [pattern for pattern, source in config.exclude if source == label]
            for pattern in patterns:
                add(pattern, label, from_repo=from_repo)
            if label in config.found:
                detail = f"found  ·  {_count(len(rules) - before, 'exclude pattern')}"
            else:
                detail = "not found"
            layers.append(LayerStatus(label, detail, label in config.found))

            for path, syntax, source in config.ignore_files:
                if source != label:
                    continue
                file = _resolve(repo_root, path)
                name = f"{path} (listed in {label})"
                outside = os.path.isabs(os.path.expanduser(path)) or not _inside(repo_root, file)
                if from_repo and (path.startswith("~") or outside):
                    config.warnings.append(f"{label}: ignore file {path} is outside the repo; ignored")
                    layers.append(LayerStatus(name, "outside the repo; ignored", False))
                    continue
                if not file.is_file():
                    layers.append(LayerStatus(name, "not found in this repo", False))
                    continue
                text = _read_small(file, path, config)
                if text is None:
                    layers.append(LayerStatus(name, "couldn't be read", False))
                    continue
                before, skipped_before = len(rules), skipped_regex[path]
                for line in text.splitlines():
                    # A file inside the repo is repo-controlled, whoever listed it
                    add(line, path, syntax, from_repo=not outside)
                added, skipped = len(rules) - before, skipped_regex[path] - skipped_before
                detail = _count(added, f"{syntax} pattern")
                if skipped:
                    detail += f"  ·  {skipped} skipped (regex from a repo file needs trust_repo_regex)"
                layers.append(LayerStatus(name, detail, added > 0))

        for source, count in skipped_regex.items():
            config.warnings.append(
                f"{source}: skipped {_count(count, 'regex rule')} from inside the repo; set "
                f"trust_repo_regex = true in your own config to use them"
            )

        revs: set[str] = set()
        revs_text = None
        if config.ignore_revs:
            revs_file = _resolve(repo_root, config.ignore_revs)
            user_set = config.ignore_revs_source == config.user_label and config.user_label
            if not user_set and (config.ignore_revs.startswith("~") or not _inside(repo_root, revs_file)):
                config.warnings.append(f"ignore_revs {config.ignore_revs} is outside the repo; ignored")
            elif revs_file.is_file():
                revs_text = _read_small(revs_file, config.ignore_revs, config)
            if revs_text is not None:
                for line in revs_text.splitlines():
                    sha = line.strip()
                    if re.fullmatch(r"[0-9a-f]{40}", sha):
                        revs.add(sha)
                layers.append(LayerStatus(config.ignore_revs, f"{_count(len(revs), 'commit')} to skip", bool(revs)))
            else:
                layers.append(LayerStatus(config.ignore_revs, "no file in this repo", False))
        else:
            layers.append(LayerStatus("ignore_revs", "turned off", False))
        return cls(rules, revs, config, layers)

    def rule_for(self, path: str) -> Rule | None:
        """
        The last rule matching `path` (it may be a re-include), or None.
        """
        if len(path) > MAX_MATCH_PATH:
            return None
        if path not in self._verdicts:
            match = None
            for rule in self.rules:
                if rule.matches(path):
                    match = rule
            self._verdicts[path] = match
        return self._verdicts[path]

    def excludes(self, path: str) -> bool:
        rule = self.rule_for(path)
        return rule is not None and not rule.negate

    def apply(self, commits: list[CommitInfo]) -> FilterResult:
        """
        Drop excluded files' lines from each commit (new CommitInfo objects).

        Commits listed in the ignore-revs file, or whose every file is excluded,
        are dropped entirely.
        """
        result = FilterResult(commits=[])
        by_rule: Counter[str] = Counter()
        rule_files: dict[str, set[str]] = {}
        by_file: Counter[str] = Counter()
        kept_by_file: Counter[str] = Counter()
        file_rule: dict[str, str] = {}
        ignored = 0
        for commit in commits:
            result.total_lines += commit.additions + commit.deletions
            if commit.hexsha in self.ignore_revs:
                lines = commit.additions + commit.deletions
                result.excluded_lines += lines
                result.dropped_commits += 1
                by_rule[self.config.ignore_revs] += lines
                ignored += 1
                continue
            if not commit.files:
                result.commits.append(commit)
                continue

            kept = []
            for path, adds, dels in commit.files:
                rule = self.rule_for(path)
                if rule is not None and not rule.negate:
                    result.excluded_lines += adds + dels
                    by_rule[rule.label] += adds + dels
                    rule_files.setdefault(rule.label, set()).add(path)
                    by_file[path] += adds + dels
                    file_rule[path] = rule.label
                else:
                    kept.append((path, adds, dels))
                    kept_by_file[path] += adds + dels

            if len(kept) == len(commit.files):
                result.commits.append(commit)
            elif kept:
                result.commits.append(
                    replace(
                        commit,
                        files=kept,
                        additions=sum(f[1] for f in kept),
                        deletions=sum(f[2] for f in kept),
                    )
                )
            else:
                result.dropped_commits += 1

        if ignored:
            lines = by_rule.pop(self.config.ignore_revs)
            noun = "commit" if ignored == 1 else "commits"
            by_rule[f"{self.config.ignore_revs}  {ignored} {noun}"] = lines
        result.by_rule = dict(by_rule)
        result.rule_files = {label: len(paths) for label, paths in rule_files.items()}
        result.by_file = {path: (lines, file_rule[path]) for path, lines in by_file.items()}
        result.kept_by_file = dict(kept_by_file)
        return result

    def suggest_preset(self, path: str) -> str | None:
        """
        Name of a preset that is turned off but would exclude `path`, if any.
        """
        for name, patterns in PRESETS.items():
            if name in self.config.presets:
                continue
            if any(compile_glob(pattern).match(path) for pattern in patterns):
                return name
        return None


def describe(exclusions: Exclusions) -> str:
    """
    Human-readable summary of the merged rules (for gvt --show-rules).
    """
    config = exclusions.config
    available = [name for name in PRESETS if name not in config.presets]
    lines = [
        f"default mode: {config.default_mode}",
        f"presets: {', '.join(config.presets) or '(none)'}"
        + (f"  (available: {', '.join(available)})" if available else ""),
        f".gitattributes linguist rules: {'on' if config.use_gitattributes else 'off'}",
        f"regex rules from repo files: {'trusted' if config.trust_repo_regex else 'skipped (trust_repo_regex is off)'}",
        f"config files: {', '.join(config.found) or '(none found)'}",
        f"ignored commits: {len(exclusions.ignore_revs)} from {config.ignore_revs or '(disabled)'}",
        "",
        "rules (last match wins, ! re-includes):",
    ]
    lines += [f"  {rule.label}" for rule in exclusions.rules] or ["  (none)"]
    if config.warnings:
        lines += ["", "warnings:"] + [f"  {safe_text(w)}" for w in config.warnings]
    return "\n".join(lines)
