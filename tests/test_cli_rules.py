"""Tests for gvt --show-rules."""

import sys
from pathlib import Path

import pytest

from gvt.cli import main


def test_show_rules_prints_merged_rules(fixture_repo, monkeypatch, capsys):
    with open(f"{fixture_repo}/.gvt.toml", "w") as f:
        f.write('[evolution]\nexclude = ["*.csv"]\n')
    monkeypatch.chdir(fixture_repo)
    monkeypatch.setattr(sys, "argv", ["gvt", "--show-rules"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert f"Evolution exclusion rules for {fixture_repo}" in out
    assert "default mode: authored" in out
    assert "preset:lockfiles  pnpm-lock.yaml" in out
    assert ".gvt.toml  *.csv" in out


def test_show_rules_escapes_directory_name(fixture_repo, monkeypatch, capsys):
    original = Path(fixture_repo)
    renamed = original.rename(original.with_name("repo\u202eexample"))
    monkeypatch.chdir(renamed)
    monkeypatch.setattr(sys, "argv", ["gvt", "--show-rules"])
    with pytest.raises(SystemExit):
        main()
    assert "repo\\u202eexample" in capsys.readouterr().out


def test_cli_propagates_tui_failure(fixture_repo, monkeypatch):
    monkeypatch.chdir(fixture_repo)
    monkeypatch.setattr(sys, "argv", ["gvt"])
    monkeypatch.setattr("signal.signal", lambda *args: None)
    monkeypatch.setattr(
        "gvt.app.GVTApp.run", lambda app: setattr(app, "_return_code", 1)
    )

    def exit_with(code):
        raise SystemExit(code)

    monkeypatch.setattr("gvt.cli.os._exit", exit_with)
    with pytest.raises(SystemExit) as status:
        main()
    assert status.value.code == 1


def test_show_rules_reports_rules_over_the_load_limits(fixture_repo, monkeypatch, capsys):
    with open(f"{fixture_repo}/.gvt.toml", "w") as f:
        f.write('[evolution]\nignore_files = ["gone", "gone"]\n')
    monkeypatch.setattr("gvt.exclusions.MAX_RULE_FILES_PER_LOAD", 1)
    monkeypatch.chdir(fixture_repo)
    monkeypatch.setattr(sys, "argv", ["gvt", "--show-rules"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "exclusions: off" in out
    assert "exclusion rules not loaded: more than 1 ignore_files entries" in out
    assert "preset:lockfiles" not in out
