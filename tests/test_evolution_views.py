"""Tests for the calendar and frequency views, mounted in a minimal host app."""

from datetime import date, datetime, timedelta, timezone

from textual.app import App, ComposeResult

from gvt.git.repo import CommitInfo, TagInfo
from gvt.widgets.calendar_view import CalendarView
from gvt.widgets.evolution_common import PeriodChosen

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
