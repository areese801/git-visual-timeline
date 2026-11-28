"""Tests for the calendar and frequency views, mounted in a minimal host app."""

from datetime import date, datetime, timedelta, timezone

from rich.cells import cell_len
from textual.app import App, ComposeResult

from gvt.git.repo import CommitInfo, TagInfo
from gvt.widgets.calendar_view import CalendarView
from gvt.widgets.evolution_common import FileChosen, PeriodChosen
from gvt.widgets.frequency_view import FrequencyView, compact
from gvt.widgets.hotspots_view import FILE_SCOPE_MESSAGE, NO_FILES_MESSAGE, HotspotsView, fit_columns, shorten_left

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
        self.files: list[str] = []

    def compose(self) -> ComposeResult:
        yield self.view

    def on_mount(self) -> None:
        self.view.focus()

    def on_period_chosen(self, event: PeriodChosen) -> None:
        self.chosen.append(event)

    def on_file_chosen(self, event: FileChosen) -> None:
        self.files.append(event.path)


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


TODAY = date(2026, 11, 20)


def _frequency_view() -> FrequencyView:
    view = FrequencyView(tz=UTC)
    view.today = TODAY
    return view


class TestFrequencyView:
    async def test_young_history_uses_daily_bars(self):
        view = _frequency_view()
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(RECENT, TAGS)
            await pilot.pause()
            assert view.granularity == "day"
            assert view.column_width == 1
            assert view.periods[0].start == date(2026, 9, 7)
            assert view.periods[-1].start == TODAY
            assert view.periods[view.cursor].start == date(2026, 11, 18)
            status = view.status_text().plain
            assert "Wed 2026-11-18" in status
            assert "2 commits" in status
            await pilot.press("h", "h")
            assert "▲ v1.0" in view.status_text().plain  # tagged on Mon 11-16

    async def test_history_start_extends_axis_back(self):
        view = _frequency_view()
        view.history_start = date(2026, 1, 1)
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(RECENT, TAGS)
            await pilot.pause()
            assert view.granularity == "week"
            assert view.periods[0].start == date(2025, 12, 29)
            assert view.periods[-1].start == date(2026, 11, 16)
            assert view.column_width == 2  # 113 // 47 weeks

    async def test_axis_runs_to_today_past_the_last_commit(self):
        view = _frequency_view()
        view.today = date(2026, 12, 30)
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(RECENT, TAGS)
            await pilot.pause()
            assert view.granularity == "week"  # 115 days don't fit 113 columns
            assert view.periods[-1].start == date(2026, 12, 28)
            # Cursor still starts on the newest commit, not the empty current week
            assert view.periods[view.cursor].start == date(2026, 11, 16)

    async def test_monthly_when_weekly_does_not_fit(self):
        view = _frequency_view()
        host = ViewHost(view)
        async with host.run_test(size=(80, 16)) as pilot:
            view.set_data(COMMITS, TAGS)
            await pilot.pause()
            assert view.granularity == "month"
            assert view.periods[0].start == date(2024, 1, 1)
            assert view.periods[-1].start == date(2026, 11, 1)
            assert "Nov 2026" in view.status_text().plain

    async def test_cursor_moves_and_jumps(self):
        view = _frequency_view()
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(RECENT, TAGS)
            start = view.cursor
            await pilot.press("h")
            assert view.cursor == start - 1
            await pilot.press("0")
            assert view.cursor == 0
            assert "+40" in view.status_text().plain
            await pilot.press("h")
            assert view.cursor == 0
            await pilot.press("dollar_sign")
            assert view.cursor == len(view.periods) - 1

    async def test_enter_posts_period(self):
        view = _frequency_view()
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(RECENT, TAGS)
            await pilot.press("enter")
            await pilot.pause()
            event = host.chosen[0]
            assert (event.start, event.end) == (date(2026, 11, 18), date(2026, 11, 19))
            assert event.label == "Wed 2026-11-18"

    async def test_render_fills_height_with_bars_both_ways(self):
        view = _frequency_view()
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(RECENT, TAGS)
            await pilot.pause()
            lines = view.render().plain.split("\n")
            assert len(lines) == 16
            assert lines[0].lstrip().startswith("+")
            axis = [line for line in lines if "─" in line]
            assert len(axis) == 1
            # Baseline spans the axis, with the cursor drawn on it
            assert len(axis[0].rstrip()) == 7 + len(view.periods)
            assert "━" in axis[0]
            chart = "\n".join(lines[:12])
            assert "█" in chart
            assert "2026" in lines[12]
            assert "Oct" in lines[12]

    async def test_cursor_survives_rebinning(self):
        view = _frequency_view()
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


class TestCalendarSizing:
    async def test_status_line_needs_eleven_rows(self):
        view = CalendarView(tz=UTC)
        host = ViewHost(view)
        async with host.run_test(size=(120, 10)) as pilot:
            view.set_data(COMMITS, TAGS)
            await pilot.pause()
            assert "Terminal too small" in view.render().plain
            await pilot.resize_terminal(120, 11)
            await pilot.pause()
            assert "2 commits" in view.render().plain.split("\n")[-1]

    async def test_cursor_stays_visible_after_narrowing(self):
        view = CalendarView(tz=UTC)
        host = ViewHost(view)
        async with host.run_test(size=(120, 14)) as pilot:
            view.set_data(COMMITS, TAGS)
            for _ in range(50):
                await pilot.press("h")
            await pilot.resize_terminal(50, 14)
            await pilot.pause()
            first, last = view.window()
            assert first <= view.cursor_day <= last


class TestFrequencyVolumeMode:
    async def test_m_toggles_between_split_and_volume(self):
        view = _frequency_view()
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(RECENT, TAGS, base_size=1000)
            await pilot.pause()
            assert view.mode == "split"
            await pilot.press("m")
            assert view.mode == "volume"
            lines = view.render().plain.split("\n")
            assert len(lines) == 16
            assert lines[0].lstrip().startswith("1k")  # size axis top: 1,016
            assert any("size" in line[:7] for line in lines)
            assert any("churn" in line[:7] for line in lines)
            assert "size 1,016" in view.status_text().plain
            await pilot.press("m")
            assert view.mode == "split"

    async def test_status_shows_relative_churn(self):
        view = _frequency_view()
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(RECENT, TAGS, base_size=1000)
            await pilot.pause()
            # Last week: +14 −6 = 20 lines touched on ~1,016 lines
            assert "≈ 2% of size" in view.status_text().plain

    async def test_volume_bars_render_stacked(self):
        view = _frequency_view()
        host = ViewHost(view)
        async with host.run_test(size=(120, 16)) as pilot:
            view.set_data(RECENT, TAGS)
            await pilot.press("m")
            await pilot.pause()
            assert view.mode == "volume"
            chart = "\n".join(view.render().plain.split("\n")[:12])
            assert "█" in chart
            assert "━" in chart  # cursor on the baseline


def _touching(day: date, *paths: str, n: int = 0) -> CommitInfo:
    commit = _commit(day, 2 * len(paths), len(paths), n)
    commit.files = [(path, 2, 1) for path in paths]
    return commit


HOT_TODAY = date(2026, 11, 20)

HOT_COMMITS = [
    _touching(date(2026, 11, 20), "src/app.py", "README.md", n=1),
    _touching(date(2026, 11, 19), "src/app.py", n=2),
    _touching(date(2026, 11, 18), "src/app.py", "tests/test_app.py", n=3),
]


def _hotspots_view(**attrs) -> HotspotsView:
    view = HotspotsView(tz=UTC)
    view.today = HOT_TODAY
    for name, value in attrs.items():
        setattr(view, name, value)
    return view


def test_fit_columns_drops_optional_columns_as_space_runs_out():
    assert fit_columns(130, 3) == (70, ["bar", "commits", "lines", "age"])
    assert fit_columns(80, 3) == (20, ["bar", "commits", "lines", "age"])
    assert fit_columns(70, 3) == (20, ["bar", "commits", "lines"])
    assert fit_columns(40, 3) == (21, ["commits"])
    assert fit_columns(10, 3) == (1, ["commits"])


def test_shorten_left_keeps_the_end_of_the_path():
    assert shorten_left("a.py", 10) == "a.py"
    assert shorten_left("src/gvt/widgets/modals.py", 12) == "…s/modals.py"
    wide = shorten_left("日本語.py", 6)
    assert wide == "…語.py" and cell_len(wide) == 6


def test_shorten_left_handles_very_long_wide_paths():
    short = shorten_left("日本語" * 1333 + "日", 30)
    assert short.startswith("…") and cell_len(short) <= 30


class TestHotspotsView:
    async def test_rows_are_ranked_with_the_cursor_on_top(self):
        view = _hotspots_view()
        host = ViewHost(view)
        async with host.run_test(size=(100, 14)) as pilot:
            view.set_data(HOT_COMMITS, [])
            await pilot.pause()
            assert [s.path for s in view.hotspots] == ["src/app.py", "README.md", "tests/test_app.py"]
            lines = view.render().plain.splitlines()
            assert "src/app.py" in lines[0] and "3 commits" in lines[0] and "today" in lines[0]
            assert len(lines) == 14 and "last changed 2026-11-20" in lines[-1]
            assert "3 commits, 3 in the last 30 days" in view.status_text().plain

    async def test_j_and_enter_choose_the_file(self):
        view = _hotspots_view()
        host = ViewHost(view)
        async with host.run_test(size=(100, 14)) as pilot:
            view.set_data(HOT_COMMITS, [])
            await pilot.press("j", "enter")
            await pilot.pause()
            assert host.files == ["README.md"]

    async def test_ends_and_paging_scroll_the_list(self):
        commits = [_touching(HOT_TODAY - timedelta(days=i), f"f{i:02d}.py", n=i) for i in range(30)]
        view = _hotspots_view()
        host = ViewHost(view)
        async with host.run_test(size=(100, 14)) as pilot:  # 12 rows of files
            view.set_data(commits, [])
            await pilot.press("G")
            assert (view.cursor, view.top) == (29, 18)
            rendered = view.render().plain
            assert "f29.py" in rendered and "f00.py" not in rendered
            await pilot.press("g")
            assert (view.cursor, view.top) == (0, 0)
            await pilot.press("pagedown")
            assert (view.cursor, view.top) == (12, 1)
            await pilot.press("k")
            assert (view.cursor, view.top) == (11, 1)

    async def test_messages_for_file_scope_and_nothing_kept(self):
        view = _hotspots_view(scope_is_file=True)
        host = ViewHost(view)
        async with host.run_test(size=(100, 14)) as pilot:
            view.set_data(HOT_COMMITS, [])
            await pilot.pause()
            assert FILE_SCOPE_MESSAGE in view.render().plain
            view.scope_is_file = False
            view.keep = lambda path: False
            view.set_data(HOT_COMMITS, [])
            await pilot.pause()
            assert NO_FILES_MESSAGE in view.render().plain
            await pilot.press("enter")
            assert host.files == []

    async def test_names_are_shown_safely(self):
        path = "[red]x\x1b]0;T\x07.py"
        view = _hotspots_view()
        host = ViewHost(view)
        async with host.run_test(size=(100, 14)) as pilot:
            view.set_data([_touching(HOT_TODAY, path)], [])
            await pilot.pause()
            rendered = view.render().plain + view.status_text().plain
            assert "[red]x" in rendered
            assert "\x1b" not in rendered and "\x07" not in rendered
            await pilot.press("enter")
            assert host.files == [path]  # the raw path still opens the file


class TestHotspotsLayout:
    async def test_status_line_fits_at_80_columns(self):
        path = "src/gvt/widgets/a/very/deeply/nested/directory/structure/hotspots_view.py"
        view = _hotspots_view()
        host = ViewHost(view)
        async with host.run_test(size=(80, 24)) as pilot:
            view.set_data([_touching(HOT_TODAY, path)], [])
            await pilot.pause()
            lines = view.render().plain.splitlines()
            assert all(cell_len(line) <= 80 for line in lines)
            assert "last changed" in lines[-1]

    async def test_path_column_hugs_the_longest_path_on_wide_terminals(self):
        view = _hotspots_view()
        host = ViewHost(view)
        async with host.run_test(size=(170, 14)) as pilot:
            view.set_data(HOT_COMMITS, [])
            await pilot.pause()
            rendered = view.render()
            lines = rendered.plain.splitlines()
            assert lines[0].index("█") < 40
            # The cursor row's highlight spans the whole widget
            assert cell_len(lines[0]) == 170
            assert any(span.end >= len(lines[0]) and "on #283457" in str(span.style) for span in rendered.spans)

    async def test_growing_the_terminal_removes_blank_rows(self):
        commits = [_touching(HOT_TODAY - timedelta(days=i), f"f{i:02d}.py", n=i) for i in range(30)]
        view = _hotspots_view()
        host = ViewHost(view)
        async with host.run_test(size=(100, 14)) as pilot:
            view.set_data(commits, [])
            await pilot.press("G")
            assert view.top == 18
            await pilot.resize_terminal(100, 24)
            await pilot.pause()
            assert view.top == 8
