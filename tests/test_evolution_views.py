"""Tests for the calendar and frequency views, mounted in a minimal host app."""

from datetime import date, datetime, timedelta, timezone

from textual.app import App, ComposeResult

from gvt.git.repo import CommitInfo, TagInfo
from gvt.widgets.calendar_view import CalendarView
from gvt.widgets.evolution_common import PeriodChosen
from gvt.widgets.frequency_view import FrequencyView, compact

UTC = timezone.utc


def _commit(day: date, adds: int = 1, dels: int = 0, n: int = 0) -> CommitInfo:
    return CommitInfo(
        hexsha=f"{day.toordinal():034d}{n:06d}",
        date=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
        author="T",
        message=f"commit {day} #{n}",
        additions=adds,
        deletions=dels,
    )


COMMITS = [
    _commit(date(2024, 1, 3), 100, 0),
    _commit(date(2025, 3, 10), 5, 5),
    _commit(date(2026, 11, 16), 3, 1),
    _commit(date(2026, 11, 18), 10, 2, n=1),
    _commit(date(2026, 11, 18), 4, 4, n=2),
]
TAGS = [TagInfo("v1.0", "x" * 40, datetime(2026, 11, 16, 12, tzinfo=UTC))]


class ViewHost(App):
    def __init__(self, view) -> None:
        super().__init__()
        self.view = view
        self.chosen: list[PeriodChosen] = []

    def compose(self) -> ComposeResult:
        yield self.view

    def on_mount(self) -> None:
        self.view.focus()

    def on_period_chosen(self, event: PeriodChosen) -> None:
        self.chosen.append(event)


async def _mounted_calendar(pilot_size=(120, 14)):
    view = CalendarView(tz=UTC)
    host = ViewHost(view)
    return host, view, pilot_size


class TestCalendarView:
    async def test_cursor_starts_on_newest_day(self):
        host, view, size = await _mounted_calendar()
        async with host.run_test(size=size) as pilot:
            view.set_data(COMMITS, TAGS)
            await pilot.pause()
            assert view.cursor_day == date(2026, 11, 18)
            status = view.status_text().plain
            assert "Wed 2026-11-18" in status
            assert "2 commits" in status
            assert "+14" in status and "−6" in status

    async def test_cannot_move_past_newest(self):
        host, view, size = await _mounted_calendar()
        async with host.run_test(size=size) as pilot:
            view.set_data(COMMITS, TAGS)
            await pilot.press("j", "l")
            assert view.cursor_day == date(2026, 11, 18)

    async def test_h_moves_a_week_and_k_a_day(self):
        host, view, size = await _mounted_calendar()
        async with host.run_test(size=size) as pilot:
            view.set_data(COMMITS, TAGS)
            await pilot.press("h")
            assert view.cursor_day == date(2026, 11, 11)
            await pilot.press("k")
            assert view.cursor_day == date(2026, 11, 10)

    async def test_tag_shown_in_status(self):
        host, view, size = await _mounted_calendar()
        async with host.run_test(size=size) as pilot:
            view.set_data(COMMITS, TAGS)
            await pilot.press("k", "k")
            assert view.cursor_day == date(2026, 11, 16)
            assert "▲ v1.0" in view.status_text().plain

    async def test_page_back_a_year_and_clamp_at_oldest(self):
        host, view, size = await _mounted_calendar()
        async with host.run_test(size=size) as pilot:
            view.set_data(COMMITS, TAGS)
            await pilot.press("left_square_bracket")
            assert view.cursor_day == date(2026, 11, 18) - timedelta(weeks=52)
            await pilot.press("left_square_bracket", "left_square_bracket", "left_square_bracket")
            first, _ = view.window()
            assert first == date(2024, 1, 1)  # Monday of the oldest commit's week
            assert view.cursor_day >= date(2024, 1, 1)
            await pilot.press("right_square_bracket", "right_square_bracket", "right_square_bracket")
            await pilot.press("right_square_bracket")
            assert view.cursor_day == date(2026, 11, 18)

    async def test_moving_past_left_edge_scrolls_window(self):
        host, view, size = await _mounted_calendar()
        async with host.run_test(size=size) as pilot:
            view.set_data(COMMITS, TAGS)
            first_before, _ = view.window()
            for _ in range(view.weeks):
                await pilot.press("h")
            first_after, _ = view.window()
            assert first_after < first_before
            assert first_after <= view.cursor_day

    async def test_enter_posts_period_for_cursor_day(self):
        host, view, size = await _mounted_calendar()
        async with host.run_test(size=size) as pilot:
            view.set_data(COMMITS, TAGS)
            await pilot.press("enter")
            await pilot.pause()
            assert len(host.chosen) == 1
            event = host.chosen[0]
            assert (event.start, event.end) == (date(2026, 11, 18), date(2026, 11, 19))
            assert event.label == "Wed 2026-11-18"

    async def test_render_has_grid_tags_and_status(self):
        host, view, size = await _mounted_calendar()
        async with host.run_test(size=size) as pilot:
            view.set_data(COMMITS, TAGS)
            await pilot.pause()
            lines = view.render().plain.split("\n")
            assert lines[1].startswith("Mon")
            assert lines[3].startswith("Wed")
            assert lines[8].rstrip().endswith("v1.0▲")
            assert "2 commits" in lines[-1]
            assert view.cell_width == 2
            assert len(lines[1]) == 4 + 53 * 2

    async def test_narrow_terminal_uses_single_width_cells(self):
        host, view, _ = await _mounted_calendar()
        async with host.run_test(size=(70, 14)) as pilot:
            view.set_data(COMMITS, TAGS)
            await pilot.pause()
            assert view.cell_width == 1
            assert view.weeks == 53

    async def test_message_replaces_chart(self):
        host, view, size = await _mounted_calendar()
        async with host.run_test(size=size) as pilot:
            await pilot.pause()
            assert "Loading" in view.render().plain
            view.set_data([], [])
            assert "No commits" in view.render().plain


def test_compact_numbers():
    assert compact(950) == "950"
    assert compact(1000) == "1k"
    assert compact(1234) == "1.2k"
    assert compact(3_400_000) == "3.4M"


RECENT = [
    _commit(date(2026, 9, 7), 40, 10),
    _commit(date(2026, 10, 14), 8, 30),
    _commit(date(2026, 11, 18), 10, 2, n=1),
    _commit(date(2026, 11, 18), 4, 4, n=2),
]


class TestFrequencyView:
    async def test_weekly_when_history_fits(self):
        view = FrequencyView(tz=UTC)
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(RECENT, TAGS)
            await pilot.pause()
            assert view.granularity == "week"
            assert view.periods[0].start == date(2026, 9, 7)
            assert view.periods[-1].start == date(2026, 11, 16)
            assert view.cursor == len(view.periods) - 1
            status = view.status_text().plain
            assert "Week of 2026-11-16" in status
            assert "2 commits" in status
            assert "▲ v1.0" in status

    async def test_monthly_when_weekly_does_not_fit(self):
        view = FrequencyView(tz=UTC)
        host = ViewHost(view)
        async with host.run_test(size=(80, 16)) as pilot:
            view.set_data(COMMITS, TAGS)
            await pilot.pause()
            assert view.granularity == "month"
            assert view.periods[0].start == date(2024, 1, 1)
            assert "Nov 2026" in view.status_text().plain

    async def test_cursor_moves_and_jumps(self):
        view = FrequencyView(tz=UTC)
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(RECENT, TAGS)
            await pilot.press("h")
            assert view.cursor == len(view.periods) - 2
            await pilot.press("0")
            assert view.cursor == 0
            assert "+40" in view.status_text().plain
            await pilot.press("h")
            assert view.cursor == 0
            await pilot.press("dollar_sign")
            assert view.cursor == len(view.periods) - 1

    async def test_enter_posts_period(self):
        view = FrequencyView(tz=UTC)
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(RECENT, TAGS)
            await pilot.press("enter")
            await pilot.pause()
            event = host.chosen[0]
            assert (event.start, event.end) == (date(2026, 11, 16), date(2026, 11, 23))
            assert event.label == "Week of 2026-11-16"

    async def test_render_fills_height_with_bars_both_ways(self):
        view = FrequencyView(tz=UTC)
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(RECENT, TAGS)
            await pilot.pause()
            lines = view.render().plain.split("\n")
            assert len(lines) == 16
            assert lines[0].lstrip().startswith("+")
            axis = [line for line in lines if "─" in line]
            assert len(axis) == 1
            chart = "\n".join(lines[:12])
            assert "█" in chart
            assert "2026" in lines[12]

    async def test_cursor_survives_rebinning(self):
        view = FrequencyView(tz=UTC)
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(COMMITS, TAGS)
            await pilot.pause()
            assert view.granularity == "month"  # 35 months fit 113 columns
            await pilot.resize_terminal(40, 16)
            await pilot.pause()
            assert view.granularity == "year"  # 35 months don't fit 33 columns
            assert view.periods[view.cursor].start == date(2026, 1, 1)
            assert view.status_text().plain.startswith("2026")
