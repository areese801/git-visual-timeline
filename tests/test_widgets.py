"""Tests for gvt widgets."""

from datetime import datetime, timezone

from gvt.git.repo import CommitInfo
from gvt.widgets.timeline import _heatmap_color, _tick_height


def _make_commit(adds=10, dels=5, msg="test commit"):
    return CommitInfo(
        hexsha="abc1234567890",
        date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        author="Test",
        message=msg,
        additions=adds,
        deletions=dels,
    )


def test_heatmap_color_pure_adds():
    color = _heatmap_color(100, 0)
    assert color == "#9ece6a"  # green


def test_heatmap_color_pure_deletes():
    color = _heatmap_color(0, 100)
    assert color == "#f7768e"  # red


def test_heatmap_color_mixed():
    color = _heatmap_color(50, 50)
    assert color == "#e0af68"  # amber


def test_heatmap_color_zero():
    color = _heatmap_color(0, 0)
    assert color == "#565f89"  # dim


def test_tick_height_zero():
    assert _tick_height(0) == 1


def test_tick_height_small():
    assert _tick_height(10) == 1


def test_tick_height_large():
    assert _tick_height(100) == 4


def test_tick_height_capped():
    assert _tick_height(1000) == 4


def test_commit_info_extra_lines():
    c = _make_commit(msg="line1\nline2\nline3")
    assert c.extra_lines == 2
    assert c.first_line == "line1"


def test_commit_info_short_hash():
    c = _make_commit()
    assert c.short_hash == "abc1234"
    assert len(c.short_hash) == 7


def test_timeline_step_mode_cursors():
    """With no pins, left_cursor is cursor-1 and right_cursor is cursor."""
    from gvt.widgets.timeline import TimelineWidget
    tw = TimelineWidget()
    commits = [_make_commit(msg=f"commit {i}") for i in range(5)]
    tw.commits = commits
    tw.cursor = 3
    assert tw.left_cursor == 2
    assert tw.right_cursor == 3


def test_timeline_step_mode_at_zero():
    """At first commit with no pins, left and right are both 0."""
    from gvt.widgets.timeline import TimelineWidget
    tw = TimelineWidget()
    commits = [_make_commit(msg=f"commit {i}") for i in range(5)]
    tw.commits = commits
    tw.cursor = 0
    assert tw.left_cursor == 0
    assert tw.right_cursor == 0


def test_timeline_pinned_range():
    """With both pins set, left/right reflect the pinned range."""
    from gvt.widgets.timeline import TimelineWidget
    tw = TimelineWidget()
    commits = [_make_commit(msg=f"commit {i}") for i in range(5)]
    tw.commits = commits
    tw.pin_start = 1
    tw.pin_end = 3
    assert tw.left_cursor == 1
    assert tw.right_cursor == 3
    assert tw.pins_locked


def test_timeline_pinned_range_reversed():
    """Pins in reverse order still produce correct left/right."""
    from gvt.widgets.timeline import TimelineWidget
    tw = TimelineWidget()
    commits = [_make_commit(msg=f"commit {i}") for i in range(5)]
    tw.commits = commits
    tw.pin_start = 4
    tw.pin_end = 1
    assert tw.left_cursor == 1
    assert tw.right_cursor == 4


def test_timeline_one_pin_live_preview():
    """With one pin, range previews from pin to cursor."""
    from gvt.widgets.timeline import TimelineWidget
    tw = TimelineWidget()
    commits = [_make_commit(msg=f"commit {i}") for i in range(5)]
    tw.commits = commits
    tw.pin_start = 1
    tw.cursor = 3
    assert tw.has_pins
    assert not tw.pins_locked
    assert tw.left_cursor == 1
    assert tw.right_cursor == 3
