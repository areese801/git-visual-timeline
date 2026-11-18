"""Tests for evolution exclusion rules: patterns, presets, config layers, filtering."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from gvt.exclusions import (
    DEFAULT_PRESETS,
    PRESETS,
    Exclusions,
    describe,
    gitattributes_rules,
    glob_to_regex,
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
        assert bool(glob_to_regex(pattern).match(path)) is expected


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
        exclusions = Exclusions.load(str(repo), user_config=None)
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
        assert "re:([" in warnings

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
    assert layers[".clocignore (listed in .gvt.toml)"] == ("2 regex patterns", True)
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
