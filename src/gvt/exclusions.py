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


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """
    Compile a gitignore-style glob into a regex matched against repo-relative paths.

    A pattern with no "/" (other than a trailing one) matches at any depth; a
    pattern containing "/" is anchored at the repo root. A trailing "/" matches
    only directories (anything beneath them). "*" stays within a path segment,
    "**" crosses segments, "?" and [classes] work as in gitignore.
    """
    dir_only = pattern.endswith("/")
    body = pattern.rstrip("/")
    anchored = "/" in body
    body = body.lstrip("/")

    out = []
    i = 0
    while i < len(body):
        if body.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif body.startswith("**", i):
            out.append(".*")
            i += 2
        elif body[i] == "*":
            out.append("[^/]*")
            i += 1
        elif body[i] == "?":
            out.append("[^/]")
            i += 1
        elif body[i] == "[" and "]" in body[i + 1:]:
            end = body.index("]", i + 1)
            cls = body[i + 1:end]
            if cls.startswith("!"):
                cls = "^" + cls[1:]
            out.append(f"[{cls}]")
            i = end + 1
        else:
            out.append(re.escape(body[i]))
            i += 1

    prefix = "" if anchored else "(?:.*/)?"
    suffix = "/.*" if dir_only else "(?:/.*)?"
    return re.compile(f"^{prefix}{''.join(out)}{suffix}$")


@dataclass(frozen=True)
class Rule:
    """
    One exclusion pattern and where it came from.
    """

    pattern: str
    source: str
    negate: bool = False
    regex: bool = False
    compiled: re.Pattern[str] = field(default=re.compile(""), compare=False, hash=False, repr=False)
    # The line as written, for listings
    text: str = field(default="", compare=False)

    def matches(self, path: str) -> bool:
        if self.regex:
            return self.compiled.search(path) is not None
        return self.compiled.match(path) is not None

    @property
    def label(self) -> str:
        """
        "source  pattern" as shown in rule listings.
        """
        text = self.text or self.pattern
        if self.negate and not text.startswith("!"):
            text = "!" + text
        return f"{self.source}  {text}"


def parse_pattern(text: str, source: str, syntax: str = "glob") -> Rule | None:
    """
    Parse one pattern line.

    :param text: Pattern as written: "!" negates, "re:" switches to a regex.
        Blank lines and "#" comments return None.
    :param source: Layer label for listings (e.g. ".gvt.toml").
    :param syntax: Default syntax for the line, "glob" or "regex".
    :raises ValueError: If a regular expression doesn't compile.
    """
    line = text.strip()
    if not line or line.startswith("#"):
        return None
    negate = line.startswith("!")
    if negate:
        line = line[1:]
    regex = syntax == "regex"
    if line.startswith("re:"):
        regex = True
        line = line[3:]
    try:
        compiled = re.compile(line) if regex else glob_to_regex(line)
    except re.error as e:
        raise ValueError(f"bad pattern {text.strip()!r} in {source}: {e}") from e
    return Rule(
        pattern=line, source=source, negate=negate, regex=regex, compiled=compiled, text=text.strip()
    )


def gitattributes_rules(text: str) -> list[Rule]:
    """
    Rules from .gitattributes lines that set or unset linguist attributes.

    "linguist-generated" / "=true" excludes; "-linguist-generated" / "=false"
    re-includes.
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
            rule = parse_pattern(pattern, ".gitattributes")
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
    # Label of the user layer (its path, shortened)
    user_label: str = ""
    # Config files that exist, by label
    found: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _read_layer(path: Path, label: str, config: ExclusionConfig) -> None:
    """
    Merge one config file into `config` (scalars override, lists append).
    """
    if not path.is_file():
        return
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
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
    _read_layer(Path(repo_root) / REPO_CONFIG_NAME, REPO_CONFIG_NAME, config)
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

        def add(text: str, source: str, syntax: str = "glob") -> None:
            try:
                rule = parse_pattern(text, source, syntax)
            except ValueError as e:
                config.warnings.append(str(e))
                return
            if rule:
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
            try:
                found = gitattributes_rules(attributes.read_text())
                rules += found
                layers.append(LayerStatus(".gitattributes", _count(len(found), "linguist rule"), bool(found)))
            except (OSError, UnicodeDecodeError) as e:
                config.warnings.append(f"couldn't read .gitattributes: {e}")
                layers.append(LayerStatus(".gitattributes", "couldn't be read", False))
        else:
            layers.append(LayerStatus(".gitattributes", "no file in this repo", False))

        for label in (config.user_label, REPO_CONFIG_NAME):
            if not label:
                continue
            before = len(rules)
            patterns = [pattern for pattern, source in config.exclude if source == label]
            for pattern in patterns:
                add(pattern, label)
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
                if not file.is_file():
                    layers.append(LayerStatus(name, "not found in this repo", False))
                    continue
                try:
                    lines = file.read_text().splitlines()
                except (OSError, UnicodeDecodeError) as e:
                    config.warnings.append(f"couldn't read {path}: {e}")
                    layers.append(LayerStatus(name, "couldn't be read", False))
                    continue
                before = len(rules)
                for line in lines:
                    add(line, path, syntax)
                layers.append(LayerStatus(name, _count(len(rules) - before, f"{syntax} pattern"), True))

        revs: set[str] = set()
        if config.ignore_revs:
            revs_file = _resolve(repo_root, config.ignore_revs)
            if revs_file.is_file():
                for line in revs_file.read_text().splitlines():
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
            if any(glob_to_regex(pattern).match(path) for pattern in patterns):
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
        f"config files: {', '.join(config.found) or '(none found)'}",
        f"ignored commits: {len(exclusions.ignore_revs)} from {config.ignore_revs or '(disabled)'}",
        "",
        "rules (last match wins, ! re-includes):",
    ]
    lines += [f"  {rule.label}" for rule in exclusions.rules] or ["  (none)"]
    if config.warnings:
        lines += ["", "warnings:"] + [f"  {w}" for w in config.warnings]
    return "\n".join(lines)
