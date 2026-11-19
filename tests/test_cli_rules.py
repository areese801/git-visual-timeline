"""Tests for gvt --show-rules."""

import sys

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
