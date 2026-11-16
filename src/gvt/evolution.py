"""
Pure binning and layout helpers for the Evolution views.

Nothing here touches git or Textual: functions take CommitInfo/TagInfo lists and
dates and return plain data, so the calendar and frequency widgets stay thin and
this logic stays unit-testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Iterable, Literal

from gvt.git.repo import CommitInfo, TagInfo

Granularity = Literal["week", "month", "year"]

# Eighth blocks growing up from the baseline, indexed by eighths filled (0-8)
UP_BLOCKS = " ▁▂▃▄▅▆▇█"

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

CALENDAR_WEEKS = 53


@dataclass
class DayStats:
    """
    Commit count and line totals for one bucket of time.
    """

    commits: int = 0
    additions: int = 0
    deletions: int = 0

    def add(self, commit: CommitInfo) -> None:
        self.commits += 1
        self.additions += commit.additions
        self.deletions += commit.deletions


@dataclass
class PeriodStats(DayStats):
    """
    DayStats for a week, month, or year starting on `start`.
    """

    start: date = date.min


def local_day(dt: datetime, tz: tzinfo | None = None) -> date:
    """
    Calendar day of a timestamp in `tz` (the local time zone when None).
    """
    return dt.astimezone(tz).date()


def bucket_by_day(commits: Iterable[CommitInfo], tz: tzinfo | None = None) -> dict[date, DayStats]:
    """
    Group commits by local calendar day.
    """
    days: dict[date, DayStats] = {}
    for commit in commits:
        days.setdefault(local_day(commit.date, tz), DayStats()).add(commit)
    return days


def week_start(d: date) -> date:
    """
    Monday of the ISO week containing `d`.
    """
    return d - timedelta(days=d.weekday())


def calendar_window(anchor: date, weeks: int = CALENDAR_WEEKS) -> tuple[date, date]:
    """
    First Monday and last Sunday of a `weeks`-wide calendar ending on `anchor`'s week.
    """
    last_monday = week_start(anchor)
    return last_monday - timedelta(weeks=weeks - 1), last_monday + timedelta(days=6)


def _nearest_rank(sorted_values: list[int], pct: float) -> int:
    """
    Nearest-rank percentile of an ascending, non-empty list.
    """
    rank = max(1, math.ceil(pct * len(sorted_values)))
    return sorted_values[rank - 1]


def quantile_levels(values: Iterable[int]) -> list[int]:
    """
    Three shade thresholds: quartiles of the non-zero values.

    A count c gets level 1 if c <= t1, 2 if c <= t2, 3 if c <= t3, else 4.
    """
    nonzero = sorted(v for v in values if v > 0)
    if not nonzero:
        return [1, 1, 1]
    return [_nearest_rank(nonzero, q) for q in (0.25, 0.5, 0.75)]


def level_for(count: int, thresholds: list[int]) -> int:
    """
    Shade level 0-4 for a count, given quantile_levels() thresholds.
    """
    if count <= 0:
        return 0
    return 1 + sum(1 for t in thresholds if count > t)


def period_start(d: date, granularity: Granularity) -> date:
    """
    First day of the week (Monday), month, or year containing `d`.
    """
    if granularity == "week":
        return week_start(d)
    if granularity == "month":
        return d.replace(day=1)
    return date(d.year, 1, 1)


def next_period(start: date, granularity: Granularity) -> date:
    """
    Start of the period after the one starting on `start`.
    """
    if granularity == "week":
        return start + timedelta(weeks=1)
    if granularity == "month":
        if start.month == 12:
            return date(start.year + 1, 1, 1)
        return date(start.year, start.month + 1, 1)
    return date(start.year + 1, 1, 1)


def count_periods(first: date, last: date, granularity: Granularity) -> int:
    """
    Number of periods from the one containing `first` to the one containing `last`.
    """
    if granularity == "week":
        return (week_start(last) - week_start(first)).days // 7 + 1
    if granularity == "month":
        return (last.year - first.year) * 12 + last.month - first.month + 1
    return last.year - first.year + 1


def choose_granularity(first: date, last: date, width: int) -> Granularity:
    """
    Finest granularity whose period count fits in `width` columns.
    """
    for granularity in ("week", "month"):
        if count_periods(first, last, granularity) <= width:
            return granularity
    return "year"


def bin_periods(
    commits: Iterable[CommitInfo], granularity: Granularity, tz: tzinfo | None = None
) -> list[PeriodStats]:
    """
    Contiguous, zero-filled periods from the oldest to the newest commit.
    """
    by_start: dict[date, PeriodStats] = {}
    for commit in commits:
        start = period_start(local_day(commit.date, tz), granularity)
        by_start.setdefault(start, PeriodStats(start=start)).add(commit)
    if not by_start:
        return []

    periods = []
    current, last = min(by_start), max(by_start)
    while current <= last:
        periods.append(by_start.get(current, PeriodStats(start=current)))
        current = next_period(current, granularity)
    return periods


def period_label(start: date, granularity: Granularity) -> str:
    """
    Human label for a period, e.g. 'Week of 2026-10-12', 'Oct 2026', '2026'.
    """
    if granularity == "week":
        return f"Week of {start.isoformat()}"
    if granularity == "month":
        return f"{MONTH_NAMES[start.month - 1]} {start.year}"
    return str(start.year)


def percentile_cap(values: Iterable[int], pct: float = 0.95) -> int:
    """
    Bar scale cap: nearest-rank percentile of non-zero values, at least 1.
    """
    nonzero = sorted(v for v in values if v > 0)
    if not nonzero:
        return 1
    return max(1, _nearest_rank(nonzero, pct))


def bar_cells(value: int, cap: int, height: int) -> tuple[int, int, bool]:
    """
    Split a bar into full cells plus a partial cell in eighths.

    :returns: (full_cells, remainder_eighths 0-7, clipped). Any non-zero value
        gets at least one eighth so it stays visible; values above `cap` fill
        the whole height and report clipped=True.
    """
    if value <= 0 or height <= 0:
        return 0, 0, False
    if value > cap:
        return height, 0, True
    eighths = max(1, round(value / cap * height * 8))
    return eighths // 8, eighths % 8, False


def place_labels(positions: Iterable[tuple[int, str]], width: int, marker: str = "") -> str:
    """
    Lay out labels on a single row.

    Each marker (if any) is always drawn at its column; its name follows it. When
    the name would run past the right edge it goes before the marker instead.
    A name is dropped when it would overlap another marker or name, or touch the
    next item without a one-cell gap.
    """
    row = [" "] * width
    items = sorted((col, name) for col, name in positions if 0 <= col < width)

    if marker:
        for col, _ in items:
            row[col] = marker

    def fits(start: int, end: int, gap_before: bool, gap_after: bool) -> bool:
        """
        Cells [start, end) are free, with blank neighbors where required.
        """
        if start < 0 or end > width or any(c != " " for c in row[start:end]):
            return False
        if gap_before and start > 0 and row[start - 1] != " ":
            return False
        if gap_after and end < width and row[end] != " ":
            return False
        return True

    offset = len(marker)
    for col, name in items:
        # After the marker (the marker itself separates it from the left)
        start, end = col + offset, col + offset + len(name)
        if fits(start, end, gap_before=not marker, gap_after=True):
            row[start:end] = list(name)
        # Otherwise before the marker, when running off the right edge
        elif marker and end > width and fits(col - len(name), col, gap_before=True, gap_after=False):
            row[col - len(name):col] = list(name)
    return "".join(row)


def month_labels(first_monday: date, weeks: int, cell_width: int) -> str:
    """
    Month names above the first calendar column of each month (January shows the year).
    """
    positions = []
    for i in range(weeks):
        monday = first_monday + timedelta(weeks=i)
        sunday = monday + timedelta(days=6)
        first_of_month = sunday.replace(day=1)
        if monday <= first_of_month <= sunday:
            name = MONTH_NAMES[first_of_month.month - 1]
            if first_of_month.month == 1:
                name = f"Jan'{first_of_month.year % 100:02d}"
            positions.append((i * cell_width, name))
    return place_labels(positions, weeks * cell_width)


def axis_labels(starts: list[date], granularity: Granularity) -> list[tuple[int, str]]:
    """
    Time-axis labels for a list of period starts, as (column, text).

    Long spans get a label at each new year; spans under two years label each
    month (with the year on January and on the first column).
    """
    if not starts:
        return []
    short = (granularity == "week" and len(starts) < 104) or (
        granularity == "month" and len(starts) < 24
    )

    labels = [(0, str(starts[0].year))]
    for i in range(1, len(starts)):
        prev, cur = starts[i - 1], starts[i]
        if cur.year != prev.year:
            labels.append((i, str(cur.year)))
        elif short and cur.month != prev.month:
            labels.append((i, MONTH_NAMES[cur.month - 1]))
    return labels


def tags_between(tags: Iterable[TagInfo], start: date, end: date, tz: tzinfo | None = None) -> list[str]:
    """
    Names of tags whose commit falls on a local day in [start, end).
    """
    return [t.name for t in tags if start <= local_day(t.date, tz) < end]
