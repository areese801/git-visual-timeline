"""
GitHub-style contribution calendar for the Evolution screen.
"""

from __future__ import annotations

from datetime import date, timedelta

from rich.text import Text

from gvt.evolution import (
    CALENDAR_WEEKS,
    DayStats,
    bucket_by_day,
    calendar_window,
    level_for,
    local_day,
    month_labels,
    place_labels,
    quantile_levels,
    tags_between,
    week_start,
)
from gvt.widgets.evolution_common import (
    COLOR_DIM,
    COLOR_GREEN,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_TEXT,
    EvolutionView,
    PeriodChosen,
    plural,
)

COLOR_CURSOR_BG = "#7aa2f7"
COLOR_CURSOR_FG = "#1a1b26"

LEVEL_CHARS = ["·", "░", "▒", "▓", "█"]
DAY_LABELS = ["Mon", "", "Wed", "", "Fri", "", ""]
GUTTER = 4
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Weeks moved by [ and ]
PAGE_WEEKS = 52


class CalendarView(EvolutionView):
    """
    7 x 53 grid of days shaded by commit count, ending at the newest commit.

    h/l move a week, j/k a day, [ / ] page a year, Enter lists the day's commits.
    """

    BINDINGS = [
        ("h", "move(-7)", "Prev week"),
        ("l", "move(7)", "Next week"),
        ("left", "move(-7)", "Prev week"),
        ("right", "move(7)", "Next week"),
        ("k", "move(-1)", "Prev day"),
        ("j", "move(1)", "Next day"),
        ("up", "move(-1)", "Prev day"),
        ("down", "move(1)", "Next day"),
        ("left_square_bracket", "page(-1)", "Prev year"),
        ("right_square_bracket", "page(1)", "Next year"),
        ("enter", "choose", "Commits"),
    ]

    # Month row, 7 day rows, tag row, blank, status
    min_height = 11

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._days: dict[date, DayStats] = {}
        self.oldest: date | None = None
        self.newest: date | None = None
        self.anchor: date | None = None
        self.cursor_day: date | None = None

    def on_data_changed(self) -> None:
        self._days = bucket_by_day(self.commits, self.tz)
        if self._days:
            self.oldest = min(self._days)
            self.newest = max(self._days)
        else:
            self.oldest = self.newest = None
        self.anchor = self.newest
        self.cursor_day = self.newest

    # Layout

    @property
    def cell_width(self) -> int:
        return 2 if self.size.width >= GUTTER + CALENDAR_WEEKS * 2 else 1

    @property
    def weeks(self) -> int:
        fit = (self.size.width - GUTTER) // self.cell_width
        return max(1, min(CALENDAR_WEEKS, fit))

    def window(self) -> tuple[date, date]:
        """
        First Monday and last Sunday currently shown.
        """
        assert self.anchor is not None
        return calendar_window(self.anchor, self.weeks)

    # Navigation

    def _clamp_anchor(self, anchor: date) -> date:
        """
        Keep the window between the oldest and newest commit weeks.
        """
        assert self.oldest is not None and self.newest is not None
        earliest = min(self.newest, week_start(self.oldest) + timedelta(weeks=self.weeks - 1))
        return max(earliest, min(self.newest, anchor))

    def _clamp_day(self, day: date) -> date:
        assert self.oldest is not None and self.newest is not None
        return max(week_start(self.oldest), min(self.newest, day))

    def _scroll_to_cursor(self) -> None:
        """
        Shift the window just enough to keep the cursor visible.
        """
        first, last = self.window()
        if self.cursor_day < first:
            self.anchor = self._clamp_anchor(week_start(self.cursor_day) + timedelta(weeks=self.weeks - 1))
        elif self.cursor_day > last:
            self.anchor = self._clamp_anchor(self.cursor_day)

    def on_resize(self) -> None:
        # The window width follows the terminal; keep the cursor inside it
        if self.cursor_day is not None:
            self._scroll_to_cursor()

    def action_move(self, days: int) -> None:
        if self.cursor_day is None:
            return
        self.cursor_day = self._clamp_day(self.cursor_day + timedelta(days=days))
        self._scroll_to_cursor()
        self.refresh()

    def action_page(self, direction: int) -> None:
        if self.cursor_day is None:
            return
        delta = timedelta(weeks=PAGE_WEEKS * direction)
        self.anchor = self._clamp_anchor(self.anchor + delta)
        self.cursor_day = self._clamp_day(self.cursor_day + delta)
        self._scroll_to_cursor()
        self.refresh()

    def action_choose(self) -> None:
        if self.cursor_day is None:
            return
        day = self.cursor_day
        self.post_message(PeriodChosen(day, day + timedelta(days=1), self._day_label(day)))

    # Rendering

    @staticmethod
    def _day_label(day: date) -> str:
        return f"{WEEKDAY_NAMES[day.weekday()]} {day.isoformat()}"

    def status_text(self) -> Text:
        if self.cursor_day is None:
            return Text()
        stats = self._days.get(self.cursor_day, DayStats())
        text = Text()
        text.append(self._day_label(self.cursor_day), style=f"bold {COLOR_TEXT}")
        text.append("  ·  ", style=COLOR_DIM)
        text.append(plural(stats.commits, "commit"), style=COLOR_TEXT)
        text.append("  ·  ", style=COLOR_DIM)
        text.append(f"+{stats.additions:,}", style=COLOR_GREEN)
        text.append(f" −{stats.deletions:,}", style=COLOR_RED)
        day = self.cursor_day
        return self._status_line(text, tags_between(self.tags, day, day + timedelta(days=1), self.tz))

    def render(self) -> Text:
        if self.message:
            return self._render_message(self.message)
        if self.anchor is None:
            return self._render_message("No commits")
        if self._too_small():
            return self._render_message("Terminal too small")

        first, last = self.window()
        cw = self.cell_width
        weeks = self.weeks
        visible = [s.commits for d, s in self._days.items() if first <= d <= last]
        thresholds = quantile_levels(visible)

        text = Text()
        text.append(" " * GUTTER + month_labels(first, weeks, cw) + "\n", style=COLOR_DIM)

        for weekday in range(7):
            text.append(f"{DAY_LABELS[weekday]:<{GUTTER}}", style=COLOR_DIM)
            for week in range(weeks):
                day = first + timedelta(weeks=week, days=weekday)
                pad = " " * (cw - 1)
                if day > self.newest:
                    text.append(" " * cw)
                    continue
                stats = self._days.get(day)
                level = level_for(stats.commits if stats else 0, thresholds)
                char = LEVEL_CHARS[level]
                if day == self.cursor_day:
                    style = f"bold {COLOR_CURSOR_FG} on {COLOR_CURSOR_BG}"
                    text.append(char if char != "·" else "◦", style=style)
                else:
                    text.append(char, style=COLOR_DIM if level == 0 else COLOR_GREEN)
                text.append(pad)
            text.append("\n")

        tag_cols = []
        for tag in self.tags:
            day = local_day(tag.date, self.tz)
            if first <= day <= last:
                tag_cols.append(((week_start(day) - first).days // 7 * cw, tag.name))
        text.append(" " * GUTTER + place_labels(tag_cols, weeks * cw, marker="▲") + "\n", style=COLOR_PURPLE)

        text.append("\n")
        text.append_text(self.status_text())
        return text
