"""Tests for the pure evolution binning and layout helpers."""

from datetime import date, datetime, timedelta, timezone

from gvt.evolution import (
    UP_BLOCKS,
    axis_labels,
    bar_cells,
    bin_periods,
    bucket_by_day,
    calendar_window,
    choose_granularity,
    level_for,
    local_day,
    month_labels,
    next_period,
    percentile_cap,
    period_label,
    period_start,
    place_labels,
    quantile_levels,
    tags_between,
    week_start,
)
from gvt.git.repo import CommitInfo, TagInfo

UTC = timezone.utc
TOKYO = timezone(timedelta(hours=9))


def _commit(dt: datetime, adds: int = 1, dels: int = 0, sha: str = "a") -> CommitInfo:
    return CommitInfo(
        hexsha=sha.ljust(40, "0"),
        date=dt,
        author="T",
        message="m",
        additions=adds,
        deletions=dels,
    )


class TestDays:
    def test_local_day_uses_given_timezone(self):
        dt = datetime(2026, 3, 1, 20, 0, tzinfo=UTC)
        assert local_day(dt, UTC) == date(2026, 3, 1)
        assert local_day(dt, TOKYO) == date(2026, 3, 2)

    def test_bucket_by_day_sums_stats(self):
        commits = [
            _commit(datetime(2026, 3, 1, 9, tzinfo=UTC), 3, 1),
            _commit(datetime(2026, 3, 1, 17, tzinfo=UTC), 2, 2),
            _commit(datetime(2026, 3, 4, 9, tzinfo=UTC), 7, 0),
        ]
        days = bucket_by_day(commits, UTC)
        assert days[date(2026, 3, 1)].commits == 2
        assert days[date(2026, 3, 1)].additions == 5
        assert days[date(2026, 3, 1)].deletions == 3
        assert days[date(2026, 3, 4)].commits == 1
        assert date(2026, 3, 2) not in days

    def test_week_start_is_monday(self):
        assert week_start(date(2026, 11, 16)) == date(2026, 11, 16)  # Monday
        assert week_start(date(2026, 11, 22)) == date(2026, 11, 16)  # Sunday

    def test_calendar_window_spans_53_weeks_ending_on_anchor_week(self):
        first, last = calendar_window(date(2026, 11, 18))
        assert first.weekday() == 0
        assert last == date(2026, 11, 22)
        assert (last - first).days + 1 == 53 * 7


class TestLevels:
    def test_quantiles_of_empty(self):
        assert quantile_levels([]) == [1, 1, 1]

    def test_quantiles_ignore_zeros(self):
        assert quantile_levels([0, 0, 4]) == [4, 4, 4]

    def test_quantiles_spread(self):
        assert quantile_levels(list(range(1, 101))) == [25, 50, 75]

    def test_level_for(self):
        thresholds = [25, 50, 75]
        assert level_for(0, thresholds) == 0
        assert level_for(1, thresholds) == 1
        assert level_for(25, thresholds) == 1
        assert level_for(26, thresholds) == 2
        assert level_for(75, thresholds) == 3
        assert level_for(500, thresholds) == 4

    def test_all_equal_counts_share_a_level(self):
        thresholds = quantile_levels([2, 2, 2])
        assert {level_for(2, thresholds)} == {1}


class TestPeriods:
    def test_period_start(self):
        d = date(2026, 11, 19)
        assert period_start(d, "week") == date(2026, 11, 16)
        assert period_start(d, "month") == date(2026, 11, 1)
        assert period_start(d, "year") == date(2026, 1, 1)

    def test_next_period_rolls_over(self):
        assert next_period(date(2026, 12, 28), "week") == date(2027, 1, 4)
        assert next_period(date(2026, 12, 1), "month") == date(2027, 1, 1)
        assert next_period(date(2026, 1, 1), "year") == date(2027, 1, 1)

    def test_choose_granularity(self):
        first = date(2024, 1, 1)
        assert choose_granularity(first, date(2024, 6, 1), 80) == "week"
        assert choose_granularity(first, date(2026, 1, 1), 80) == "month"
        assert choose_granularity(date(1990, 1, 1), date(2026, 1, 1), 80) == "year"

    def test_bin_periods_zero_fills_gaps(self):
        commits = [
            _commit(datetime(2026, 1, 5, tzinfo=UTC), 10, 2),
            _commit(datetime(2026, 1, 6, tzinfo=UTC), 1, 1),
            _commit(datetime(2026, 1, 26, tzinfo=UTC), 4, 0),
        ]
        periods = bin_periods(commits, "week", UTC)
        assert [p.start for p in periods] == [
            date(2026, 1, 5),
            date(2026, 1, 12),
            date(2026, 1, 19),
            date(2026, 1, 26),
        ]
        assert [p.commits for p in periods] == [2, 0, 0, 1]
        assert periods[0].additions == 11
        assert periods[0].deletions == 3

    def test_bin_periods_empty(self):
        assert bin_periods([], "month", UTC) == []

    def test_period_label(self):
        assert period_label(date(2026, 10, 12), "week") == "Week of 2026-10-12"
        assert period_label(date(2026, 10, 1), "month") == "Oct 2026"
        assert period_label(date(2026, 1, 1), "year") == "2026"


class TestBars:
    def test_cap_ignores_outlier(self):
        values = [10] * 30 + [5000]
        assert percentile_cap(values) == 10

    def test_cap_never_zero(self):
        assert percentile_cap([]) == 1
        assert percentile_cap([0, 0]) == 1

    def test_bar_cells_zero(self):
        assert bar_cells(0, 10, 4) == (0, 0, False)

    def test_bar_cells_exact_and_remainder(self):
        assert bar_cells(10, 10, 4) == (4, 0, False)
        assert bar_cells(5, 10, 4) == (2, 0, False)
        assert bar_cells(3, 16, 4) == (0, 6, False)

    def test_bar_cells_tiny_value_still_visible(self):
        assert bar_cells(1, 10_000, 4) == (0, 1, False)

    def test_bar_cells_clipped(self):
        assert bar_cells(50, 10, 4) == (4, 0, True)

    def test_up_blocks(self):
        assert UP_BLOCKS[0] == " "
        assert UP_BLOCKS[8] == "█"
        assert len(UP_BLOCKS) == 9


class TestLabels:
    def test_place_labels_markers_and_names(self):
        row = place_labels([(0, "v1"), (6, "v2")], 12, marker="▲")
        assert row == "▲v1   ▲v2   "

    def test_place_labels_drops_overlapping_names_keeps_markers(self):
        row = place_labels([(0, "v1.0.0"), (3, "v2")], 12, marker="▲")
        assert row == "▲  ▲v2      "

    def test_place_labels_needs_a_gap_before_next_marker(self):
        row = place_labels([(0, "abc"), (4, "x")], 8, marker="▲")
        assert row == "▲   ▲x  "

    def test_place_labels_flips_left_at_right_edge(self):
        row = place_labels([(9, "v2")], 10, marker="▲")
        assert row == "       v2▲"

    def test_place_labels_ignores_out_of_range(self):
        row = place_labels([(-1, "a"), (20, "b")], 10, marker="▲")
        assert row == " " * 10

    def test_place_labels_without_marker(self):
        assert place_labels([(2, "Jan")], 8) == "  Jan   "

    def test_month_labels_mark_first_week_of_each_month(self):
        first = date(2026, 1, 26)  # Monday; Feb 1 falls in this week
        row = month_labels(first, weeks=6, cell_width=2)
        assert row.startswith("Feb")
        # Mar 1 2026 is a Sunday -> week starting Feb 23 = column 4 -> offset 8
        assert row[8:11] == "Mar"

    def test_month_labels_show_year_on_january(self):
        row = month_labels(date(2025, 12, 29), weeks=2, cell_width=4)
        assert row.startswith("Jan'26")

    def test_axis_labels_years_for_long_spans(self):
        starts = [date(2020 + i // 12, i % 12 + 1, 1) for i in range(48)]
        labels = axis_labels(starts, "month")
        assert labels[0] == (0, "2020")
        assert (12, "2021") in labels
        assert all(name.isdigit() for _, name in labels)

    def test_axis_labels_months_for_short_spans(self):
        starts = [date(2026, m, 1) for m in range(1, 7)]
        labels = axis_labels(starts, "month")
        assert labels[0] == (0, "2026")
        assert (1, "Feb") in labels

    def test_tags_between(self):
        tags = [
            TagInfo("v1", "a" * 40, datetime(2026, 1, 5, 12, tzinfo=UTC)),
            TagInfo("v2", "b" * 40, datetime(2026, 2, 5, 12, tzinfo=UTC)),
        ]
        assert tags_between(tags, date(2026, 1, 1), date(2026, 2, 1), UTC) == ["v1"]
        assert tags_between(tags, date(2026, 1, 1), date(2026, 3, 1), UTC) == ["v1", "v2"]
        assert tags_between(tags, date(2026, 3, 1), date(2026, 4, 1), UTC) == []
