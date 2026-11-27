"""Tests for the pure evolution binning and layout helpers."""

from datetime import date, datetime, timedelta, timezone

from gvt.evolution import (
    HOTSPOT_MIN_HALF_LIFE_DAYS,
    UP_BLOCKS,
    PeriodStats,
    age_label,
    axis_labels,
    bar_cells,
    bin_periods,
    bucket_by_day,
    calendar_window,
    choose_granularity,
    frequency_layout,
    hbar,
    hotspot_half_life,
    level_for,
    local_day,
    month_labels,
    next_period,
    percentile_cap,
    period_label,
    period_start,
    periods_before,
    place_labels,
    quantile_levels,
    rank_hotspots,
    relative_churn,
    running_sizes,
    size_axis,
    tags_between,
    volume_cells,
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
        assert period_start(d, "day") == d
        assert period_start(d, "week") == date(2026, 11, 16)
        assert period_start(d, "month") == date(2026, 11, 1)
        assert period_start(d, "year") == date(2026, 1, 1)

    def test_next_period_rolls_over(self):
        assert next_period(date(2026, 12, 31), "day") == date(2027, 1, 1)
        assert next_period(date(2026, 12, 28), "week") == date(2027, 1, 4)
        assert next_period(date(2026, 12, 1), "month") == date(2027, 1, 1)
        assert next_period(date(2026, 1, 1), "year") == date(2027, 1, 1)

    def test_choose_granularity(self):
        first = date(2024, 1, 1)
        assert choose_granularity(first, date(2024, 2, 15), 80) == "day"
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

    def test_bin_periods_extends_to_start_and_end(self):
        commits = [_commit(datetime(2026, 1, 14, tzinfo=UTC))]
        periods = bin_periods(
            commits, "week", UTC, start=date(2025, 12, 31), end=date(2026, 1, 28)
        )
        assert periods[0].start == date(2025, 12, 29)
        assert periods[-1].start == date(2026, 1, 26)
        assert [p.commits for p in periods] == [0, 0, 1, 0, 0]

    def test_periods_before(self):
        assert periods_before(date(2026, 3, 2), "day", 2) == date(2026, 2, 28)
        assert periods_before(date(2026, 11, 16), "week", 2) == date(2026, 11, 2)
        assert periods_before(date(2026, 2, 1), "month", 3) == date(2025, 11, 1)
        assert periods_before(date(2026, 1, 1), "year", 5) == date(2021, 1, 1)

    def test_frequency_layout_spans_project_history(self):
        # A new file in a repo that began in April: axis starts at the repo's start
        granularity, start, width = frequency_layout(
            date(2026, 11, 15), date(2026, 11, 17), 113, history_start=date(2026, 4, 2)
        )
        assert granularity == "week"  # 230 days don't fit 113 columns; 33 weeks do
        assert start == date(2026, 3, 30)
        assert width == 3  # 113 // 33

    def test_frequency_layout_young_repo_uses_daily_bars(self):
        granularity, start, width = frequency_layout(date(2026, 8, 30), date(2026, 11, 17), 113)
        assert granularity == "day"  # 80 days fit
        assert start == date(2026, 8, 30)
        assert width == 1

    def test_frequency_layout_brand_new_repo_shows_minimum_periods(self):
        granularity, start, width = frequency_layout(date(2026, 11, 16), date(2026, 11, 17), 113)
        assert granularity == "day"
        assert start == date(2026, 11, 10)  # 8 days ending today
        assert width == 4

    def test_frequency_layout_long_history_keeps_its_span(self):
        granularity, start, width = frequency_layout(date(2024, 1, 3), date(2026, 11, 17), 113)
        assert granularity == "month"
        assert width == 3  # 113 // 35 months
        assert start == date(2024, 1, 1)

    def test_bin_periods_empty(self):
        assert bin_periods([], "month", UTC) == []

    def test_period_label(self):
        assert period_label(date(2026, 10, 13), "day") == "Tue 2026-10-13"
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


class TestVolume:
    def test_running_sizes_accumulate_net_lines(self):
        periods = [
            PeriodStats(start=date(2026, 1, 5), additions=100, deletions=0),
            PeriodStats(start=date(2026, 1, 12)),
            PeriodStats(start=date(2026, 1, 19), additions=10, deletions=40),
        ]
        assert running_sizes(periods) == [100, 100, 70]
        assert running_sizes(periods, base=1000) == [1100, 1100, 1070]

    def test_size_axis_starts_at_zero_for_young_code(self):
        assert size_axis([0, 0, 302]) == (0, 302)

    def test_size_axis_zooms_in_on_mature_code(self):
        assert size_axis([9000, 9500, 10500]) == (8625, 10500)

    def test_size_axis_flat(self):
        assert size_axis([500, 500]) == (450, 500)
        assert size_axis([0, 0]) == (0, 1)

    def test_volume_cells_stack_adds_under_dels(self):
        assert volume_cells(8, 8, 16, 2) == [("█", "add"), ("█", "del")]

    def test_volume_cells_split_inside_one_cell(self):
        assert volume_cells(4, 4, 16, 2) == [("▄", "add_on_del"), (" ", "")]

    def test_volume_cells_clipped(self):
        assert volume_cells(100, 0, 10, 2) == [("█", "add"), ("█", "clip")]

    def test_volume_cells_empty(self):
        assert volume_cells(0, 0, 10, 2) == [(" ", ""), (" ", "")]

    def test_relative_churn(self):
        assert relative_churn(50, 1000, 1000) == 0.05
        assert relative_churn(323, 0, 302) == 323 / 302
        assert relative_churn(10, 0, 0) is None


def _touch(day: date, *paths: str, adds: int = 2, dels: int = 1) -> CommitInfo:
    commit = _commit(datetime(day.year, day.month, day.day, 12, tzinfo=UTC), adds * len(paths), dels * len(paths))
    commit.files = [(path, adds, dels) for path in paths]
    return commit


class TestHotspots:
    TODAY = date(2026, 1, 21)

    def test_half_life_is_a_quarter_of_the_span(self):
        assert hotspot_half_life(date(2025, 1, 1), date(2026, 1, 1)) == 365 / 4

    def test_half_life_has_a_floor(self):
        assert hotspot_half_life(date(2026, 1, 1), self.TODAY) == HOTSPOT_MIN_HALF_LIFE_DAYS
        # A start after today (clock skew) still gets the floor
        assert hotspot_half_life(date(2026, 2, 1), self.TODAY) == HOTSPOT_MIN_HALF_LIFE_DAYS

    def test_weight_halves_each_half_life(self):
        commits = [_touch(date(2026, 1, d), "a.py") for d in (21, 11, 1)]
        [spot] = rank_hotspots(commits, self.TODAY, half_life=10, tz=UTC)
        assert spot.score == 1 + 0.5 + 0.25
        assert (spot.commits, spot.recent_commits) == (3, 1)
        assert (spot.additions, spot.deletions) == (6, 3)
        assert spot.last_change == datetime(2026, 1, 21, 12, tzinfo=UTC)

    def test_future_commits_weigh_one(self):
        [spot] = rank_hotspots([_touch(date(2026, 3, 1), "a.py")], self.TODAY, half_life=10, tz=UTC)
        assert spot.score == 1
        assert spot.recent_commits == 1

    def test_recent_change_outranks_an_old_busy_file(self):
        commits = [_touch(date(2026, 1, 1), "old.py") for _ in range(3)] + [_touch(self.TODAY, "new.py")]
        ranked = rank_hotspots(commits, self.TODAY, half_life=10, tz=UTC)
        assert [s.path for s in ranked] == ["new.py", "old.py"]  # 1.0 vs 0.75

    def test_ties_go_to_more_commits_then_path(self):
        commits = [
            _touch(date(2026, 1, 11), "two.py"),
            _touch(date(2026, 1, 11), "two.py"),
            _touch(self.TODAY, "b.py", "a.py"),
        ]
        ranked = rank_hotspots(commits, self.TODAY, half_life=10, tz=UTC)
        assert [s.path for s in ranked] == ["two.py", "a.py", "b.py"]  # all score 1.0

    def test_keep_drops_paths_and_is_asked_once_per_path(self):
        commits = [_touch(self.TODAY, "kept.py", "gone.py"), _touch(self.TODAY, "gone.py")]
        asked = []

        def keep(path: str) -> bool:
            asked.append(path)
            return path != "gone.py"

        ranked = rank_hotspots(commits, self.TODAY, 10, keep, UTC)
        assert [s.path for s in ranked] == ["kept.py"]
        assert asked.count("gone.py") == 1

    def test_binary_files_count_as_commits(self):
        [spot] = rank_hotspots([_touch(self.TODAY, "logo.png", adds=0, dels=0)], self.TODAY, 10, tz=UTC)
        assert (spot.commits, spot.additions, spot.deletions) == (1, 0, 0)

    def test_no_commits(self):
        assert rank_hotspots([], self.TODAY, 10) == []

    def test_hbar(self):
        assert hbar(1.0, 4) == "████"
        assert hbar(0.5, 4) == "██  "
        assert hbar(0.25, 2) == "▌ "
        assert hbar(0.001, 4) == "▏   "  # anything above zero shows
        assert hbar(0.0, 3) == "   "
        assert hbar(2.0, 2) == "██"

    def test_age_label(self):
        today = self.TODAY
        assert age_label(today, today) == "today"
        assert age_label(today + timedelta(days=3), today) == "today"
        assert age_label(today - timedelta(days=1), today) == "1d ago"
        assert age_label(today - timedelta(days=13), today) == "13d ago"
        assert age_label(today - timedelta(days=14), today) == "2w ago"
        assert age_label(today - timedelta(days=60), today) == "2mo ago"
        assert age_label(today - timedelta(days=729), today) == "24mo ago"
        assert age_label(today - timedelta(days=730), today) == "2y ago"
