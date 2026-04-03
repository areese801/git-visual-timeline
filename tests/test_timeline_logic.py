"""Tests for TimelineWidget logic (no rendering required)."""

from datetime import datetime, timedelta, timezone

from gvt.git.repo import CommitInfo
from gvt.widgets.timeline import TimelineWidget


def _make_commit(idx=0, adds=10, dels=5, msg="test", date=None, is_wip=False):
    if date is None:
        date = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=idx)
    hexsha = f"{idx:040d}" if not is_wip else "0" * 40
    return CommitInfo(
        hexsha=hexsha,
        date=date,
        author="Test",
        message=msg,
        additions=adds,
        deletions=dels,
        is_wip=is_wip,
    )


def _make_timeline(n=5):
    tw = TimelineWidget()
    commits = [_make_commit(idx=i, msg=f"commit {i}") for i in range(n)]
    tw._all_commits = commits
    tw.commits = commits
    tw.cursor = len(commits) - 1
    tw.pin_start = None
    tw.pin_end = None
    return tw, commits


class TestSetCommits:
    def test_resets_pins(self):
        tw = TimelineWidget()
        tw.pin_start = 2
        tw.pin_end = 4
        commits = [_make_commit(idx=i) for i in range(3)]
        tw.set_commits(commits)
        assert tw.pin_start is None
        assert tw.pin_end is None

    def test_resets_cursor_to_last(self):
        tw = TimelineWidget()
        commits = [_make_commit(idx=i) for i in range(5)]
        tw.set_commits(commits)
        assert tw.cursor == 4

    def test_empty_commits(self):
        tw = TimelineWidget()
        tw.set_commits([])
        assert tw.cursor == 0
        assert tw.commits == []

    def test_clears_time_filter(self):
        tw = TimelineWidget()
        tw.time_filter = "1m"
        commits = [_make_commit(idx=i) for i in range(3)]
        tw.set_commits(commits)
        assert tw.time_filter == ""


class TestApplyTimeFilter:
    def _make_tw_with_dates(self):
        """Create timeline with commits spanning 2 years.

        Using offsets that are well within boundaries to avoid edge cases.
        """
        tw = TimelineWidget()
        now = datetime.now(tz=timezone.utc)
        commits = []
        # 5 commits: 2y ago, 300d ago, 100d ago, 15d ago, 3d ago
        offsets = [730, 300, 100, 15, 3]
        for i, days_ago in enumerate(offsets):
            commits.append(_make_commit(
                idx=i,
                msg=f"commit {i}",
                date=now - timedelta(days=days_ago),
            ))
        tw.set_commits(commits)
        return tw

    def test_filter_1w(self):
        tw = self._make_tw_with_dates()
        tw.apply_time_filter("1w")
        # Only the 3-day-ago commit is within 1 week
        assert len(tw.commits) == 1

    def test_filter_1m(self):
        tw = self._make_tw_with_dates()
        tw.apply_time_filter("1m")
        # 15d and 3d commits are within 30 days
        assert len(tw.commits) == 2

    def test_filter_3m(self):
        tw = self._make_tw_with_dates()
        tw.apply_time_filter("3m")
        # 15d and 3d are within 90 days
        assert len(tw.commits) == 2

    def test_filter_6m(self):
        tw = self._make_tw_with_dates()
        tw.apply_time_filter("6m")
        # 100d, 15d, 3d are within 180 days
        assert len(tw.commits) == 3

    def test_filter_1y(self):
        tw = self._make_tw_with_dates()
        tw.apply_time_filter("1y")
        # 300d, 100d, 15d, 3d are within 365 days
        assert len(tw.commits) == 4

    def test_filter_date_string(self):
        tw = self._make_tw_with_dates()
        now = datetime.now(tz=timezone.utc)
        cutoff = now - timedelta(days=200)
        date_str = cutoff.strftime("%Y-%m-%d")
        tw.apply_time_filter(date_str)
        # Should include 6m, 1m, 1w (within 200 days)
        assert len(tw.commits) == 3

    def test_filter_empty_clears(self):
        tw = self._make_tw_with_dates()
        tw.apply_time_filter("1w")
        assert len(tw.commits) < 5
        tw.apply_time_filter("")
        assert len(tw.commits) == 5

    def test_filter_invalid_keeps_all(self):
        tw = self._make_tw_with_dates()
        tw.apply_time_filter("not-a-date")
        assert len(tw.commits) == 5

    def test_filter_resets_pins(self):
        tw = self._make_tw_with_dates()
        tw.pin_start = 1
        tw.pin_end = 3
        tw.apply_time_filter("1m")
        assert tw.pin_start is None
        assert tw.pin_end is None

    def test_filter_resets_cursor_to_last(self):
        tw = self._make_tw_with_dates()
        tw.apply_time_filter("1m")
        assert tw.cursor == len(tw.commits) - 1


class TestCursorMovement:
    def test_step_mode_left_right(self):
        tw, _ = _make_timeline(5)
        tw.cursor = 3
        # Step mode: left = cursor-1, right = cursor
        assert tw.left_cursor == 2
        assert tw.right_cursor == 3

    def test_step_mode_at_zero(self):
        tw, _ = _make_timeline(5)
        tw.cursor = 0
        assert tw.left_cursor == 0
        assert tw.right_cursor == 0

    def test_one_pin_live_preview(self):
        tw, _ = _make_timeline(5)
        tw.pin_start = 1
        tw.cursor = 4
        assert tw.left_cursor == 1
        assert tw.right_cursor == 4

    def test_one_pin_cursor_before_pin(self):
        tw, _ = _make_timeline(5)
        tw.pin_start = 3
        tw.cursor = 1
        assert tw.left_cursor == 1
        assert tw.right_cursor == 3

    def test_both_pins_locked(self):
        tw, _ = _make_timeline(5)
        tw.pin_start = 1
        tw.pin_end = 3
        tw.cursor = 0  # cursor doesn't affect range
        assert tw.left_cursor == 1
        assert tw.right_cursor == 3

    def test_pins_reversed(self):
        tw, _ = _make_timeline(5)
        tw.pin_start = 4
        tw.pin_end = 1
        assert tw.left_cursor == 1
        assert tw.right_cursor == 4

    def test_cursor_cant_go_below_zero(self):
        tw, _ = _make_timeline(5)
        tw.cursor = 0
        tw.action_move_cursor(-1)
        assert tw.cursor == 0

    def test_cursor_cant_go_above_max(self):
        tw, _ = _make_timeline(5)
        tw.cursor = 4
        tw.action_move_cursor(1)
        assert tw.cursor == 4

    def test_move_cursor_forward(self):
        tw, _ = _make_timeline(5)
        tw.cursor = 2
        tw.action_move_cursor(1)
        assert tw.cursor == 3

    def test_move_cursor_backward(self):
        tw, _ = _make_timeline(5)
        tw.cursor = 2
        tw.action_move_cursor(-1)
        assert tw.cursor == 1

    def test_jump_first(self):
        tw, _ = _make_timeline(5)
        tw.cursor = 4
        tw.action_jump_first()
        assert tw.cursor == 0

    def test_jump_last(self):
        tw, _ = _make_timeline(5)
        tw.cursor = 0
        tw.action_jump_last()
        assert tw.cursor == 4

    def test_move_cursor_empty_commits(self):
        tw = TimelineWidget()
        tw.commits = []
        tw.action_move_cursor(1)  # should not crash
        assert tw.cursor == 0


class TestPinActions:
    def test_pin_cycle(self):
        tw, _ = _make_timeline(5)
        tw.cursor = 1
        # First pin: sets start
        tw.action_pin()
        assert tw.pin_start == 1
        assert tw.pin_end is None
        assert tw.has_pins
        assert not tw.pins_locked

        # Second pin: sets end
        tw.cursor = 3
        tw.action_pin()
        assert tw.pin_start == 1
        assert tw.pin_end == 3
        assert tw.pins_locked

        # Third pin: clears
        tw.action_pin()
        assert tw.pin_start is None
        assert tw.pin_end is None
        assert not tw.has_pins

    def test_snap_pin_start_only(self):
        tw, _ = _make_timeline(5)
        tw.pin_start = 1
        tw.cursor = 3
        tw.action_snap_pin()
        assert tw.pin_start == 3

    def test_snap_pin_closer_to_start(self):
        tw, _ = _make_timeline(10)
        tw.pin_start = 2
        tw.pin_end = 8
        tw.cursor = 3  # closer to start
        tw.action_snap_pin()
        assert tw.pin_start == 3
        assert tw.pin_end == 8

    def test_snap_pin_closer_to_end(self):
        tw, _ = _make_timeline(10)
        tw.pin_start = 2
        tw.pin_end = 8
        tw.cursor = 7  # closer to end
        tw.action_snap_pin()
        assert tw.pin_start == 2
        assert tw.pin_end == 7

    def test_snap_pin_equal_distance_favors_start(self):
        tw, _ = _make_timeline(10)
        tw.pin_start = 2
        tw.pin_end = 8
        tw.cursor = 5  # equidistant
        tw.action_snap_pin()
        assert tw.pin_start == 5

    def test_snap_pin_no_pins_does_nothing(self):
        tw, _ = _make_timeline(5)
        tw.cursor = 2
        tw.action_snap_pin()
        assert tw.pin_start is None

    def test_clear_pins(self):
        tw, _ = _make_timeline(5)
        tw.pin_start = 1
        tw.pin_end = 3
        tw.action_clear_pins()
        assert tw.pin_start is None
        assert tw.pin_end is None

    def test_clear_pins_no_pins(self):
        tw, _ = _make_timeline(5)
        tw.action_clear_pins()  # should not crash
        assert tw.pin_start is None

    def test_pin_empty_commits(self):
        tw = TimelineWidget()
        tw.commits = []
        tw.action_pin()  # should not crash
        assert tw.pin_start is None


class TestWIPCommit:
    def test_wip_short_hash(self):
        c = _make_commit(is_wip=True)
        assert c.short_hash == "WIP"

    def test_non_wip_short_hash(self):
        c = _make_commit(idx=42)
        assert c.short_hash != "WIP"
        assert len(c.short_hash) == 7
