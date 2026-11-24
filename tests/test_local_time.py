"""Dates are shown in the local time zone everywhere in gvt."""

import os
import time
from datetime import datetime, timezone

import pytest
from git import Repo
from textual.app import App
from textual.widgets import Static

from gvt.git.repo import CommitInfo, GitRepo
from gvt.widgets.commit_bar import CommitMessageBar
from gvt.widgets.modals import CommitDetailPopup

# 20:00 UTC on Mar 1 is already Mar 2 in Tokyo (UTC+9)
LATE_UTC = datetime(2026, 3, 1, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def tokyo(monkeypatch):
    """
    Run the test with the process time zone set to Asia/Tokyo.
    """
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _commit() -> CommitInfo:
    return CommitInfo("a" * 40, LATE_UTC, "T", "msg", 1, 0)


def test_commit_bar_shows_local_time(tokyo):
    row = CommitMessageBar()._render_row(_commit(), "[", "#7aa2f7", False).plain
    assert "2026-03-02 05:00" in row


async def test_commit_detail_shows_local_time(tokyo):
    app = App()
    async with app.run_test() as pilot:
        popup = CommitDetailPopup(_commit())
        app.push_screen(popup)
        await pilot.pause()
        text = " ".join(str(w.render()) for w in popup.query(Static))
    assert "2026-03-02 05:00:00" in text


def test_blame_dates_are_local(tokyo, tmp_path):
    repo_dir = str(tmp_path / "r")
    os.makedirs(repo_dir)
    repo = Repo.init(repo_dir)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@example.com")
    with open(os.path.join(repo_dir, "a.txt"), "w") as f:
        f.write("x\n")
    repo.git.add("a.txt")
    stamp = "2026-03-01T20:00:00+00:00"
    repo.git.commit("-m", "late", env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
    sha = repo.head.commit.hexsha
    assert GitRepo(repo_dir).get_blame("a.txt", sha)[0][2] == "2026-03-02"


async def test_commit_toast_title_shows_local_date(tokyo, tmp_path, monkeypatch):
    from gvt.app import GVTApp

    repo_dir = str(tmp_path / "r")
    os.makedirs(repo_dir)
    repo = Repo.init(repo_dir)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "T")
        cw.set_value("user", "email", "t@example.com")
    with open(os.path.join(repo_dir, "a.txt"), "w") as f:
        f.write("x\n")
    repo.git.add("a.txt")
    stamp = "2026-03-01T20:00:00+00:00"
    repo.git.commit("-m", "late", env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})

    app = GVTApp(repo_path=repo_dir, initial_file="a.txt")
    titles = []
    original = app.notify
    monkeypatch.setattr(app, "notify", lambda msg, **k: titles.append(k.get("title", "")) or original(msg, **k))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert any("2026-03-02" in t for t in titles)
