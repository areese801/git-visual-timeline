"""Tests for evolution exclusion rules: patterns, presets, config layers, filtering."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from gvt.exclusions import (
    DEFAULT_PRESETS,
    MAX_WARNING_LENGTH,
    MAX_WARNINGS,
    PRESETS,
    Exclusions,
    describe,
    gitattributes_rules,
    compile_glob,
    load_config,
    parse_pattern,
    user_config_path,
)
from gvt.git.repo import CommitInfo


def _commit(sha: str, files: list[tuple[str, int, int]]) -> CommitInfo:
    return CommitInfo(
        hexsha=sha.ljust(40, "0"),
        date=datetime(2026, 11, 1, tzinfo=timezone.utc),
        author="T",
        message=sha,
        additions=sum(f[1] for f in files),
        deletions=sum(f[2] for f in files),
        files=files,
    )


class TestGlobs:
    @pytest.mark.parametrize(
        "pattern, path, expected",
        [
            ("pnpm-lock.yaml", "pnpm-lock.yaml", True),
            ("pnpm-lock.yaml", "apps/web/pnpm-lock.yaml", True),
            ("*.min.js", "static/app.min.js", True),
            ("*.min.js", "static/app.js", False),
            ("vendor/", "vendor/lib/x.go", True),
            ("vendor/", "pkg/vendor/lib/x.go", True),
            ("vendor/", "vendor", False),
            ("docs", "docs/guide.md", True),
            ("/docs", "docs/guide.md", True),
            ("/docs", "pkg/docs/guide.md", False),
            ("src/*.py", "src/app.py", True),
            ("src/*.py", "src/sub/app.py", False),
            ("src/**/*.py", "src/sub/deep/app.py", True),
            ("**/migrations/meta/*_snapshot.json", "packages/db/migrations/meta/0022_snapshot.json", True),
            ("**/migrations/meta/*_snapshot.json", "packages/db/migrations/0022_init.sql", False),
            ("data/[ab].csv", "data/a.csv", True),
            ("data/[!ab].csv", "data/a.csv", False),
            ("file?.txt", "file1.txt", True),
        ],
    )
    def test_glob_matching(self, pattern, path, expected):
        assert compile_glob(pattern).match(path) is expected


class TestParsePattern:
    def test_comments_and_blanks_are_skipped(self):
        assert parse_pattern("# note", "x") is None
        assert parse_pattern("   ", "x") is None

    def test_negation(self):
        rule = parse_pattern("!docs/keep.md", "x")
        assert rule.negate and rule.pattern == "docs/keep.md"
        assert rule.matches("docs/keep.md")

    def test_regex_prefix(self):
        rule = parse_pattern("re:^docs/prototype/", "x")
        assert rule.regex
        assert rule.matches("docs/prototype/a.html")
        assert not rule.matches("src/docs/prototype/a.html")

    def test_regex_syntax_for_ignore_files(self):
        rule = parse_pattern("^src/db/seed/data/", ".clocignore", syntax="regex")
        assert rule.regex and rule.matches("src/db/seed/data/x.json")

    def test_bad_regex_raises(self):
        with pytest.raises(ValueError):
            parse_pattern("re:([", "x")


class TestPresets:
    def test_defaults(self):
        assert DEFAULT_PRESETS == ("lockfiles", "minified", "generated", "vendored")
        assert set(PRESETS) == {"lockfiles", "minified", "generated", "vendored", "docs", "data"}

    @pytest.mark.parametrize(
        "path",
        [
            "pnpm-lock.yaml",
            "frontend/package-lock.json",
            "uv.lock",
            "go.sum",
            "static/app.min.js",
            "packages/db/migrations/meta/0022_snapshot.json",
            "web/__snapshots__/x.snap",
            "vendor/github.com/x/y.go",
        ],
    )
    def test_default_presets_exclude(self, path, tmp_path):
        exclusions = Exclusions.load(str(tmp_path), user_config=None)
        assert exclusions.excludes(path)

    @pytest.mark.parametrize("path", ["src/app.py", "README.md", "data/domains.json"])
    def test_default_presets_keep_code_docs_and_data(self, path, tmp_path):
        exclusions = Exclusions.load(str(tmp_path), user_config=None)
        assert not exclusions.excludes(path)


class TestGitattributes:
    def test_linguist_attributes(self):
        rules = gitattributes_rules(
            "# comment\n"
            "*.pb.go linguist-generated=true\n"
            "third_party/** linguist-vendored\n"
            "docs/** linguist-documentation\n"
            "docs/api.md -linguist-documentation\n"
            "*.sh text eol=lf\n"
        )
        assert [(r.pattern, r.negate) for r in rules] == [
            ("*.pb.go", False),
            ("third_party/**", False),
            ("docs/**", False),
            ("docs/api.md", True),
        ]
        assert all(r.source == ".gitattributes" for r in rules)

    def test_false_value_re_includes(self):
        rules = gitattributes_rules("gen/** linguist-generated=false\n")
        assert rules[0].negate


class TestConfigLayers:
    def _write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_defaults_without_files(self, tmp_path):
        config = load_config(str(tmp_path), user_config=None)
        assert config.default_mode == "authored"
        assert config.presets == list(DEFAULT_PRESETS)
        assert config.use_gitattributes
        assert config.warnings == []

    def test_repo_overrides_user_scalars_and_appends_patterns(self, tmp_path):
        user = self._write(
            tmp_path / "home" / "config.toml",
            '[evolution]\ndefault_mode = "everything"\npresets = ["lockfiles", "docs"]\n'
            'exclude = ["*.csv"]\n',
        )
        repo = tmp_path / "repo"
        self._write(repo / ".gvt.toml", '[evolution]\ndefault_mode = "authored"\nexclude = ["!keep.csv"]\n')
        config = load_config(str(repo), user_config=user)
        assert config.default_mode == "authored"
        assert config.presets == ["lockfiles", "docs"]
        assert [p for p, _ in config.exclude] == ["*.csv", "!keep.csv"]

        exclusions = Exclusions.load(str(repo), user_config=user)
        assert exclusions.excludes("report.csv")
        assert not exclusions.excludes("keep.csv")  # repo layer wins (last match)
        assert exclusions.excludes("README.md")  # docs preset from the user layer

    def test_ignore_files_with_regex_syntax(self, tmp_path):
        repo = tmp_path / "repo"
        self._write(repo / ".clocignore", "# loc extras\n^docs/prototype/\n^src/db/seed/data/\n")
        self._write(
            repo / ".gvt.toml",
            '[evolution]\nignore_files = [{ path = ".clocignore", syntax = "regex" }]\n',
        )
        trusting = tmp_path / "user.toml"
        trusting.write_text("[evolution]\ntrust_repo_regex = true\n")
        exclusions = Exclusions.load(str(repo), user_config=trusting)
        assert exclusions.excludes("docs/prototype/a.html")
        assert exclusions.excludes("src/db/seed/data/x.json")
        assert not exclusions.excludes("src/app.py")
        assert any(r.source == ".clocignore" for r in exclusions.rules)

    def test_missing_ignore_file_is_skipped(self, tmp_path):
        repo = tmp_path / "repo"
        self._write(repo / ".gvt.toml", '[evolution]\nignore_files = [".clocignore"]\n')
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert exclusions.config.warnings == []

    def test_bad_toml_and_unknown_preset_become_warnings(self, tmp_path):
        repo = tmp_path / "repo"
        self._write(repo / ".gvt.toml", "[evolution\n")
        assert any(".gvt.toml" in w for w in load_config(str(repo), user_config=None).warnings)

        self._write(repo / ".gvt.toml", '[evolution]\npresets = ["lockfiles", "nope"]\nexclude = ["re:(["]\n')
        exclusions = Exclusions.load(str(repo), user_config=None)
        warnings = " ".join(exclusions.config.warnings)
        assert "nope" in warnings
        assert "skipped 1 regex rule" in warnings

    def test_gitattributes_layer_can_be_disabled(self, tmp_path):
        repo = tmp_path / "repo"
        self._write(repo / ".gitattributes", "gen/** linguist-generated\n")
        assert Exclusions.load(str(repo), user_config=None).excludes("gen/a.py")
        self._write(repo / ".gvt.toml", "[evolution]\nuse_gitattributes = false\n")
        assert not Exclusions.load(str(repo), user_config=None).excludes("gen/a.py")

    def test_ignore_revs(self, tmp_path):
        repo = tmp_path / "repo"
        sha = "f" * 40
        self._write(repo / ".git-blame-ignore-revs", f"# formatting\n{sha}\n")
        assert Exclusions.load(str(repo), user_config=None).ignore_revs == {sha}


class TestApply:
    def test_filters_files_and_recomputes_totals(self, tmp_path):
        exclusions = Exclusions.load(str(tmp_path), user_config=None)
        commits = [
            _commit("a", [("src/app.py", 10, 2), ("pnpm-lock.yaml", 500, 400)]),
            _commit("b", [("pnpm-lock.yaml", 30, 30)]),
            _commit("c", [("src/util.py", 5, 0)]),
        ]
        result = exclusions.apply(commits)
        assert [c.message for c in result.commits] == ["a", "c"]
        assert (result.commits[0].additions, result.commits[0].deletions) == (10, 2)
        assert result.commits[0].files == [("src/app.py", 10, 2)]
        assert result.excluded_lines == 960
        assert result.dropped_commits == 1
        assert result.by_rule == {"preset:lockfiles  pnpm-lock.yaml": 960}
        # The original commits are untouched
        assert commits[0].additions == 510

    def test_ignore_revs_drop_whole_commits(self, tmp_path):
        (tmp_path / ".git-blame-ignore-revs").write_text("b".ljust(40, "0") + "\n")
        exclusions = Exclusions.load(str(tmp_path), user_config=None)
        result = exclusions.apply([_commit("a", [("x.py", 1, 0)]), _commit("b", [("y.py", 900, 900)])])
        assert [c.message for c in result.commits] == ["a"]
        assert result.excluded_lines == 1800
        assert result.by_rule == {".git-blame-ignore-revs  1 commit": 1800}

    def test_negation_keeps_file(self, tmp_path):
        (tmp_path / ".gvt.toml").write_text('[evolution]\nexclude = ["!pnpm-lock.yaml"]\n')
        exclusions = Exclusions.load(str(tmp_path), user_config=None)
        result = exclusions.apply([_commit("a", [("pnpm-lock.yaml", 3, 3)])])
        assert result.excluded_lines == 0
        assert len(result.commits) == 1


def test_describe_lists_layers_and_rules(tmp_path):
    (tmp_path / ".gvt.toml").write_text('[evolution]\nexclude = ["*.csv"]\n')
    text = describe(Exclusions.load(str(tmp_path), user_config=None))
    assert "default mode: authored" in text
    assert "presets: lockfiles, minified, generated, vendored" in text
    assert "available: docs, data" in text
    assert "preset:lockfiles" in text
    assert ".gvt.toml" in text and "*.csv" in text
    assert "last match wins" in text


def test_user_config_path_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GVT_CONFIG", str(tmp_path / "custom.toml"))
    assert user_config_path() == tmp_path / "custom.toml"
    monkeypatch.delenv("GVT_CONFIG")
    assert user_config_path().parts[-3:] == (".config", "gvt", "config.toml")


def test_default_user_config_is_read(monkeypatch, tmp_path):
    user = tmp_path / "custom.toml"
    user.write_text('[evolution]\nexclude = ["*.csv"]\n')
    monkeypatch.setenv("GVT_CONFIG", str(user))
    exclusions = Exclusions.load(str(tmp_path / "repo"))
    assert exclusions.excludes("a.csv")
    assert any(r.source.endswith("custom.toml") for r in exclusions.rules)


def test_apply_reports_files_rules_and_totals(tmp_path):
    exclusions = Exclusions.load(str(tmp_path), user_config=None)
    result = exclusions.apply([
        _commit("a", [("src/app.py", 10, 2), ("pnpm-lock.yaml", 500, 400)]),
        _commit("b", [("pnpm-lock.yaml", 30, 30), ("web/a.min.js", 7, 0)]),
    ])
    assert result.total_lines == 979
    assert result.by_file == {
        "pnpm-lock.yaml": (960, "preset:lockfiles  pnpm-lock.yaml"),
        "web/a.min.js": (7, "preset:minified  *.min.js"),
    }
    assert result.rule_files == {
        "preset:lockfiles  pnpm-lock.yaml": 1,
        "preset:minified  *.min.js": 1,
    }


def test_layers_explain_how_rules_were_built(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitattributes").write_text("gen/** linguist-generated\n")
    (repo / ".clocignore").write_text("^seed/\n^fixtures/\n")
    (repo / ".gvt.toml").write_text(
        '[evolution]\nexclude = ["*.csv"]\n'
        'ignore_files = [{ path = ".clocignore", syntax = "regex" }, ".missingignore"]\n'
    )
    exclusions = Exclusions.load(str(repo), user_config=tmp_path / "absent.toml")
    layers = {layer.name: (layer.detail, layer.active) for layer in exclusions.layers}

    assert layers["Built-in presets"] == (
        "on: lockfiles, minified, generated, vendored  ·  off: docs, data",
        True,
    )
    assert layers[".gitattributes"] == ("1 linguist rule", True)
    assert layers[str(tmp_path / "absent.toml")] == ("not found", False)
    assert layers[".gvt.toml"] == ("found  ·  1 exclude pattern", True)
    assert layers[".clocignore (listed in .gvt.toml)"] == (
        "0 regex patterns  ·  2 skipped (regex from a repo file needs trust_repo_regex)",
        False,
    )
    assert layers[".missingignore (listed in .gvt.toml)"] == ("not found in this repo", False)
    assert layers[".git-blame-ignore-revs"] == ("no file in this repo", False)
    assert [layer.name for layer in exclusions.layers][0] == "Built-in presets"


def test_kept_files_and_preset_suggestions(tmp_path):
    exclusions = Exclusions.load(str(tmp_path), user_config=None)
    result = exclusions.apply([
        _commit("a", [("src/app.py", 10, 2), ("data/domains.json", 14000, 0), ("README.md", 5, 1)]),
    ])
    assert result.kept_by_file == {"src/app.py": 12, "data/domains.json": 14000, "README.md": 6}
    assert exclusions.suggest_preset("data/domains.json") == "data"
    assert exclusions.suggest_preset("README.md") == "docs"
    assert exclusions.suggest_preset("src/app.py") is None


def test_readme_lists_every_preset_pattern():
    """
    The README's presets table must stay in sync with PRESETS.
    """
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    for name, patterns in PRESETS.items():
        row = next((line for line in readme.splitlines() if line.startswith(f"| `{name}` |")), None)
        assert row, f"preset {name} missing from the README presets table"
        for pattern in patterns:
            assert f"`{pattern}`" in row, f"{pattern} ({name}) missing from the README"
        assert ("| yes |" in row) == (name in DEFAULT_PRESETS)


class TestUntrustedRepoRules:
    """
    Rules that come from files inside a repo are attacker-controlled when the
    repo is untrusted: they must not hang gvt or read files outside the repo.
    """

    def _repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        return repo

    def test_gitattributes_patterns_are_always_globs(self, tmp_path):
        rules = gitattributes_rules("re:^(a+)+$ linguist-generated\n")
        assert rules and not rules[0].regex

    def test_repo_regex_rules_skipped_without_trust(self, tmp_path):
        repo = self._repo(tmp_path)
        (repo / ".gvt.toml").write_text('[evolution]\nexclude = ["re:^gen/", "*.csv"]\n')
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert not exclusions.excludes("gen/a.py")
        assert exclusions.excludes("a.csv")
        assert any("trust_repo_regex" in w for w in exclusions.config.warnings)

    def test_repo_regex_rules_used_when_user_trusts_them(self, tmp_path):
        repo = self._repo(tmp_path)
        (repo / ".gvt.toml").write_text('[evolution]\nexclude = ["re:^gen/"]\n')
        user = tmp_path / "user.toml"
        user.write_text("[evolution]\ntrust_repo_regex = true\n")
        assert Exclusions.load(str(repo), user_config=user).excludes("gen/a.py")

    def test_repo_cannot_grant_itself_trust(self, tmp_path):
        repo = self._repo(tmp_path)
        (repo / ".gvt.toml").write_text('[evolution]\ntrust_repo_regex = true\nexclude = ["re:^gen/"]\n')
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert not exclusions.excludes("gen/a.py")
        assert any("only read from your own config" in w for w in exclusions.config.warnings)

    def test_in_repo_regex_ignore_file_needs_trust_even_from_user_config(self, tmp_path):
        repo = self._repo(tmp_path)
        (repo / ".clocignore").write_text("^seed/\n")
        user = tmp_path / "user.toml"
        user.write_text('[evolution]\nignore_files = [{ path = ".clocignore", syntax = "regex" }]\n')
        assert not Exclusions.load(str(repo), user_config=user).excludes("seed/x.json")
        user.write_text(
            '[evolution]\ntrust_repo_regex = true\n'
            'ignore_files = [{ path = ".clocignore", syntax = "regex" }]\n'
        )
        assert Exclusions.load(str(repo), user_config=user).excludes("seed/x.json")

    def test_user_regex_outside_repo_is_trusted(self, tmp_path):
        repo = self._repo(tmp_path)
        rules_file = tmp_path / "my-rules.txt"
        rules_file.write_text("^seed/\n")
        user = tmp_path / "user.toml"
        user.write_text(f'[evolution]\nignore_files = [{{ path = "{rules_file}", syntax = "regex" }}]\n')
        assert Exclusions.load(str(repo), user_config=user).excludes("seed/x.json")

    def test_repeated_double_stars_collapse_and_match_fast(self):
        import time

        rule = parse_pattern("**/" * 12 + "zz", "x")
        start = time.time()
        for _ in range(200):
            rule.matches("a/" * 200 + "b")
        assert time.time() - start < 0.5
        assert rule.matches("deep/dir/zz")

    @pytest.mark.parametrize(
        "pattern, path",
        [
            ("*a*a*a*a*a*a*a*a*a*b", "a" * 250),
            ("**/a/**/b/**/c/**/d/**/e", "/".join(["a", "b", "c", "d"] * 40)),
            ("**/" * 40 + "x*y*z*q", "/".join(["xyz"] * 200)),
        ],
    )
    def test_pathological_globs_match_fast(self, pattern, path):
        import time

        rule = parse_pattern(pattern, "x")
        start = time.time()
        for _ in range(20):
            assert not rule.matches(path)
        assert time.time() - start < 0.5

    def test_overly_long_patterns_are_rejected(self):
        with pytest.raises(ValueError, match="too long"):
            parse_pattern("a" * 300, "x")

    def test_very_long_paths_are_not_matched(self, tmp_path):
        exclusions = Exclusions.load(str(tmp_path), user_config=None)
        assert not exclusions.excludes("a/" * 600 + "pnpm-lock.yaml")

    @pytest.mark.parametrize("entry", ["{outside}", "../outside.txt", "~/outside.txt"])
    def test_repo_config_cannot_read_files_outside_the_repo(self, tmp_path, entry):
        repo = self._repo(tmp_path)
        outside = tmp_path / "outside.txt"
        outside.write_text("TOP-SECRET\n")
        entry = entry.format(outside=outside)
        (repo / ".gvt.toml").write_text(f'[evolution]\nignore_files = ["{entry}"]\nignore_revs = "{entry}"\n')
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert "TOP-SECRET" not in describe(exclusions)
        assert any("outside the repo" in w for w in exclusions.config.warnings)

    def test_symlinked_rule_file_pointing_outside_is_refused(self, tmp_path):
        repo = self._repo(tmp_path)
        outside = tmp_path / "outside.txt"
        outside.write_text("TOP-SECRET\n")
        (repo / ".clocignore").symlink_to(outside)
        (repo / ".gvt.toml").write_text('[evolution]\nignore_files = [".clocignore"]\n')
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert "TOP-SECRET" not in describe(exclusions)

    def test_symlinked_gvt_toml_pointing_outside_is_refused(self, tmp_path):
        repo = self._repo(tmp_path)
        outside = tmp_path / "outside.toml"
        outside.write_text('[evolution]\nexclude = ["*.py"]\n')
        (repo / ".gvt.toml").symlink_to(outside)
        assert not Exclusions.load(str(repo), user_config=None).excludes("a.py")

    def test_huge_rule_files_are_skipped(self, tmp_path):
        repo = self._repo(tmp_path)
        (repo / "big.txt").write_text("*.py\n" * 200_000)
        (repo / ".gvt.toml").write_text('[evolution]\nignore_files = ["big.txt"]\n')
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert not exclusions.excludes("a.py")
        assert any("too large" in w for w in exclusions.config.warnings)


class TestHostileRuleFiles:
    """
    Second review round: inputs that could still stall, crash or leak.
    """

    def test_full_unicode_ranges_are_cheap(self):
        import time
        import tracemalloc

        tracemalloc.start()
        start = time.time()
        rule = parse_pattern("[\x00-\U0010ffff]" * 4, "x")
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert time.time() - start < 0.1 and peak < 5_000_000
        assert rule.matches("abcd") and not rule.matches("abc")

    def test_caret_negates_a_class_like_gitignore(self):
        assert compile_glob("[^ab].txt").match("c.txt")
        assert not compile_glob("[^ab].txt").match("a.txt")

    def test_empty_patterns_are_rejected(self):
        for text in ("/", "!", "!/"):
            with pytest.raises(ValueError, match="empty"):
                parse_pattern(text, "x")

    def test_trailing_double_star_needs_something_beneath(self):
        assert compile_glob("a/**").match("a/b")
        assert not compile_glob("a/**").match("a")

    def test_too_many_pattern_segments_are_rejected(self):
        with pytest.raises(ValueError, match="too many"):
            parse_pattern("**/" + "a/" * 40 + "b", "x")

    def test_rules_per_source_are_capped(self, tmp_path):
        from gvt.exclusions import MAX_RULES_PER_SOURCE

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "many.txt").write_text("".join(f"f{i}.txt\n" for i in range(MAX_RULES_PER_SOURCE + 50)))
        (repo / ".gvt.toml").write_text('[evolution]\nignore_files = ["many.txt"]\n')
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert sum(1 for r in exclusions.rules if r.source == "many.txt") == MAX_RULES_PER_SOURCE
        assert any("only the first" in w for w in exclusions.config.warnings)

    def test_apply_stops_when_asked(self, tmp_path):
        exclusions = Exclusions.load(str(tmp_path), user_config=None)
        commits = [_commit(str(i), [("a.py", 1, 0)]) for i in range(5000)]
        calls = []

        def should_stop():
            calls.append(1)
            return True

        result = exclusions.apply(commits, should_stop=should_stop)
        assert calls and result.stopped
        assert len(result.commits) < len(commits)

    @pytest.mark.parametrize(
        "text",
        [
            "evolution = 1\n",
            "[evolution]\nexclude = 5\n",
            "[evolution]\npresets = 5\n",
            "[evolution]\nignore_files = 5\n",
            "[evolution]\nignore_revs = 5\n",
            '[evolution]\nignore_revs = "a\\u0000b"\n',
            '[evolution]\nignore_files = ["a\\u0000b"]\n',
            "x = " + "[" * 50000 + "]" * 50000 + "\n",
        ],
    )
    def test_malformed_repo_config_becomes_a_warning(self, tmp_path, text):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".gvt.toml").write_text(text)
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert exclusions.config.warnings
        describe(exclusions)  # must not raise either

    def test_ignore_revs_label_is_printed_safely(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".gvt.toml").write_text('[evolution]\nignore_revs = "x\\u001b]0;T\\u0007"\n')
        text = describe(Exclusions.load(str(repo), user_config=None))
        assert "\x1b" not in text and "\x07" not in text

    def test_user_listed_relative_ignore_file_counts_as_repo_content(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        outside = tmp_path / "outside-rules.txt"
        outside.write_text("^seed/\n")
        (repo / ".clocignore").symlink_to(outside)
        user = tmp_path / "user.toml"
        user.write_text('[evolution]\nignore_files = [{ path = ".clocignore", syntax = "regex" }]\n')
        # Listed relative to the repo, so it's repo content even though it
        # resolves outside: regex needs trust
        assert not Exclusions.load(str(repo), user_config=user).excludes("seed/x.json")


def test_expensive_rules_fall_back_to_everything_within_the_budget(tmp_path, monkeypatch):
    import time

    import gvt.exclusions as exclusions_module

    monkeypatch.setattr(exclusions_module, "MATCH_BUDGET_SECONDS", 0.5)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "big.txt").write_text(("**/" + "a/" * 14 + "b\n") * 3000)
    (repo / ".gvt.toml").write_text('[evolution]\nignore_files = ["big.txt"]\n')
    exclusions = Exclusions.load(str(repo), user_config=None)
    commits = [_commit(str(i), [("/".join(["a"] * 63) + str(i), 1, 0)]) for i in range(500)]
    start = time.time()
    result = exclusions.apply(commits)
    assert time.time() - start < 2.0
    assert result.over_budget and len(result.commits) == 500
    assert any("showing everything" in w for w in exclusions.config.warnings)


def test_deep_paths_are_never_matched(tmp_path):
    exclusions = Exclusions.load(str(tmp_path), user_config=None)
    assert exclusions.excludes("/".join(["d"] * 10) + "/yarn.lock")
    assert not exclusions.excludes("/".join(["d"] * 70) + "/yarn.lock")


def test_trust_requires_a_boolean(tmp_path):
    user = tmp_path / "user.toml"
    user.write_text('[evolution]\ntrust_repo_regex = "false"\n')
    config = load_config(str(tmp_path), user)
    assert not config.trust_repo_regex and config.warnings


def test_untrusted_regex_is_skipped_before_compilation(tmp_path):
    (tmp_path / ".gvt.toml").write_text('[evolution]\nexclude = ["!re:["]\n')
    warnings = Exclusions.load(str(tmp_path), user_config=None).config.warnings
    assert any("skipped" in warning for warning in warnings)


def test_absolute_in_repo_ignore_file_needs_user_trust(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    rules = repo / "rules.txt"
    rules.write_text("^demo/\n")
    user = tmp_path / "user.toml"
    user.write_text(
        f'[evolution]\nignore_files = [{{path = "{rules}", syntax = "regex"}}]\n'
    )
    assert not Exclusions.load(str(repo), user).excludes("demo/file")


def test_relative_ignore_file_stays_in_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "outside").write_text("ordinary.txt\n")
    (repo / "rules").symlink_to(tmp_path / "outside")
    user = tmp_path / "user.toml"
    user.write_text('[evolution]\nignore_files = ["rules"]\n')
    assert not Exclusions.load(str(repo), user).excludes("ordinary.txt")


def test_attributes_honor_source_cap(monkeypatch):
    monkeypatch.setattr("gvt.exclusions.MAX_RULES_PER_SOURCE", 1)
    warnings = []
    rules = gitattributes_rules(
        "a linguist-generated\nb linguist-generated\n", warnings
    )
    assert [rule.pattern for rule in rules] == ["a"] and warnings


def test_large_commit_checks_cancellation_during_filtering(tmp_path):
    rules = Exclusions.load(str(tmp_path), user_config=None)
    commit = _commit("a", [(f"src/{i}", 1, 0) for i in range(80)])
    result = rules.apply([commit], should_stop=lambda: bool(rules._verdicts))
    assert result.stopped and len(rules._verdicts) < 80


def test_valid_presets_have_no_type_warning(tmp_path):
    (tmp_path / ".gvt.toml").write_text('[evolution]\npresets = ["lockfiles"]\n')
    assert not load_config(str(tmp_path), None).warnings


def test_rule_file_read_obeys_byte_budget(tmp_path, monkeypatch):
    (tmp_path / ".gitattributes").write_text("a linguist-generated\n")
    original = Path.stat

    def stale_stat(path, *args, **kwargs):
        data = original(path, *args, **kwargs)
        if path.name == ".gitattributes":
            values = list(data)
            values[6] = 1
            return type(data)(values)
        return data

    monkeypatch.setattr(Path, "stat", stale_stat)
    monkeypatch.setattr("gvt.exclusions.MAX_RULE_FILE_BYTES", 8)
    assert not Exclusions.load(str(tmp_path), user_config=None).excludes("a")


def test_absolute_ignore_revs_inside_repo_stays_inside(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "revisions"
    sha = "a" * 40
    external.write_text(sha)
    link = repo / "rules"
    link.symlink_to(external)
    user = tmp_path / "user.toml"
    user.write_text(f'[evolution]\nignore_revs = "{link}"\n')
    assert not Exclusions.load(str(repo), user).ignore_revs
    user.write_text(f'[evolution]\nignore_revs = "{external}"\n')
    assert Exclusions.load(str(repo), user).ignore_revs == {sha}


class TestLoadBudget:
    """
    Totals across every rule source in one Exclusions.load.
    """

    @staticmethod
    def _repo(tmp_path: Path, toml: str) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".gvt.toml").write_text(f"[evolution]\npresets = []\n{toml}")
        return repo

    @staticmethod
    def _reads(monkeypatch) -> list[tuple[str, int]]:
        """
        Record (file name, bytes requested) for every rule-file read.
        """
        reads = []
        original = Path.open

        class Recorder:
            def __init__(self, path, stream):
                self.path, self.stream = path, stream

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.stream.close()

            def read(self, size):
                reads.append((self.path.name, size))
                return self.stream.read(size)

        monkeypatch.setattr(Path, "open", lambda path, *a, **k: Recorder(path, original(path, *a, **k)))
        return reads

    def test_rules_up_to_the_limit_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gvt.exclusions.MAX_RULES_PER_LOAD", 3)
        repo = self._repo(tmp_path, 'exclude = ["a", "b", "c"]\n')
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert not exclusions.over_budget
        assert [rule.pattern for rule in exclusions.rules] == ["a", "b", "c"]

    def test_one_rule_past_the_limit_turns_exclusions_off(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gvt.exclusions.MAX_RULES_PER_LOAD", 3)
        repo = self._repo(tmp_path, 'exclude = ["a", "b", "c", "d"]\n')
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert exclusions.over_budget and exclusions.rules == []
        assert "more than 3 rules" in exclusions.config.warnings[0]

    def test_gitattributes_rules_count_toward_the_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gvt.exclusions.MAX_RULES_PER_LOAD", 1)
        repo = self._repo(tmp_path, "")
        (repo / ".gitattributes").write_text("a linguist-generated\nb linguist-vendored\n")
        assert Exclusions.load(str(repo), user_config=None).over_budget

    def test_rule_files_up_to_the_limit_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gvt.exclusions.MAX_RULE_FILES_PER_LOAD", 2)
        repo = self._repo(tmp_path, 'ignore_files = ["rules", "missing"]\n')
        (repo / "rules").write_text("a.txt\n")
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert not exclusions.over_budget and exclusions.excludes("a.txt")

    def test_repeated_entries_each_count(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gvt.exclusions.MAX_RULE_FILES_PER_LOAD", 2)
        repo = self._repo(tmp_path, 'ignore_files = ["rules", "./rules", "rules"]\n')
        (repo / "rules").write_text("a.txt\n")
        reads = self._reads(monkeypatch)
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert exclusions.over_budget and not exclusions.excludes("a.txt")
        # The third entry is refused before it is opened
        assert [name for name, _ in reads].count("rules") == 2

    def test_missing_entries_count_and_stop_before_reading(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gvt.exclusions.MAX_RULE_FILES_PER_LOAD", 2)
        repo = self._repo(tmp_path, 'ignore_files = ["gone", "gone", "rules"]\n')
        (repo / "rules").write_text("a.txt\n")
        reads = self._reads(monkeypatch)
        assert Exclusions.load(str(repo), user_config=None).over_budget
        assert "rules" not in [name for name, _ in reads]

    def test_files_up_to_the_byte_limit_load(self, tmp_path, monkeypatch):
        repo = self._repo(tmp_path, 'ignore_files = ["rules"]\n')
        (repo / "rules").write_text("a.txt\n")
        total = (repo / ".gvt.toml").stat().st_size + (repo / "rules").stat().st_size
        monkeypatch.setattr("gvt.exclusions.MAX_RULE_BYTES_PER_LOAD", total)
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert not exclusions.over_budget and exclusions.excludes("a.txt")

    def test_one_byte_past_the_limit_turns_exclusions_off(self, tmp_path, monkeypatch):
        repo = self._repo(tmp_path, 'ignore_files = ["rules"]\n')
        (repo / "rules").write_text("a.txt\n" * 1000)
        config_size = (repo / ".gvt.toml").stat().st_size
        total = config_size + (repo / "rules").stat().st_size
        monkeypatch.setattr("gvt.exclusions.MAX_RULE_BYTES_PER_LOAD", total - 1)
        reads = self._reads(monkeypatch)
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert exclusions.over_budget
        assert "over" in exclusions.config.warnings[0] and "KB" in exclusions.config.warnings[0]
        # The read asks for what's left plus one byte, not the per-file cap
        assert reads[-1] == ("rules", total - 1 - config_size + 1)

    def test_fallback_shows_all_history(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gvt.exclusions.MAX_RULE_FILES_PER_LOAD", 1)
        repo = self._repo(tmp_path, 'exclude = ["*.lock"]\nignore_files = ["gone", "gone"]\n')
        sha = "a" * 40
        (repo / ".git-blame-ignore-revs").write_text(sha + "\n")
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert exclusions.over_budget
        assert exclusions.rules == [] and exclusions.ignore_revs == set()
        assert exclusions.config.warnings[0].startswith("exclusion rules not loaded")
        assert exclusions.suggest_preset("pnpm-lock.yaml") is None
        commits = [_commit("a", [("x.lock", 5, 0)]), _commit("b", [("src.py", 1, 1)])]
        result = exclusions.apply(commits)
        assert result.commits == commits and result.excluded_lines == 0
        text = describe(exclusions)
        assert text.startswith("exclusions: off")
        assert "exclusion rules not loaded" in text and "preset:" not in text

    def test_rules_within_budget_keep_precedence_and_trust(self, tmp_path, monkeypatch):
        # A skipped repo regex doesn't count toward the limit
        monkeypatch.setattr("gvt.exclusions.MAX_RULES_PER_LOAD", 3)
        repo = self._repo(
            tmp_path, 'exclude = ["*.txt", "re:^x", "!keep.txt"]\nignore_files = ["rules"]\n'
        )
        (repo / "rules").write_text("keep.txt\n")
        exclusions = Exclusions.load(str(repo), user_config=None)
        assert not exclusions.over_budget
        assert exclusions.excludes("b.txt") and exclusions.excludes("keep.txt")
        assert not exclusions.excludes("xyz")
        assert any("skipped 1 regex rule" in w for w in exclusions.config.warnings)

    def test_repeated_presets_load_once(self, tmp_path):
        (tmp_path / ".gvt.toml").write_text('[evolution]\npresets = ["lockfiles", "lockfiles"]\n')
        assert load_config(str(tmp_path), None).presets == ["lockfiles"]


class TestWarningLimits:
    """
    A config full of problems yields a bounded list of short warnings.
    """

    @staticmethod
    def _presets(tmp_path: Path, names: list[str]) -> Exclusions:
        listed = ", ".join(f'"{name}"' for name in names)
        (tmp_path / ".gvt.toml").write_text(f"[evolution]\npresets = [{listed}]\n")
        return Exclusions.load(str(tmp_path), user_config=None)

    def test_warnings_up_to_the_limit_are_all_kept(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gvt.exclusions.MAX_WARNINGS", 3)
        warnings = self._presets(tmp_path, ["p0", "p1", "p2"]).config.warnings
        assert warnings == [f".gvt.toml: unknown preset 'p{i}'" for i in range(3)]

    def test_warnings_past_the_limit_become_a_count(self, tmp_path):
        warnings = self._presets(tmp_path, [f"p{i}" for i in range(20_000)]).config.warnings
        assert len(warnings) == MAX_WARNINGS + 1
        assert warnings[0] == ".gvt.toml: unknown preset 'p0'"
        assert warnings[MAX_WARNINGS - 1] == f".gvt.toml: unknown preset 'p{MAX_WARNINGS - 1}'"
        assert warnings[-1] == f"{20_000 - MAX_WARNINGS} more warnings not shown"

    def test_long_warnings_are_shortened(self, tmp_path):
        warnings = self._presets(tmp_path, ["p" * 100_000]).config.warnings
        assert len(warnings[0]) == MAX_WARNING_LENGTH
        assert warnings[0].startswith(".gvt.toml: unknown preset 'ppp") and warnings[0].endswith("…")
