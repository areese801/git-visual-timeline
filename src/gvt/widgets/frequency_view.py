"""GitHub Insights-style code frequency chart for the Evolution screen."""

from __future__ import annotations

from datetime import date

from rich.text import Text

from gvt.evolution import (
    UP_BLOCKS,
    Granularity,
    PeriodStats,
    axis_labels,
    bar_cells,
    bin_periods,
    choose_granularity,
    local_day,
    next_period,
    percentile_cap,
    period_label,
    period_start,
    place_labels,
    tags_between,
)
from gvt.widgets.evolution_common import (
    COLOR_AMBER,
    COLOR_DIM,
    COLOR_GREEN,
    COLOR_PURPLE,
    COLOR_RED,
    COLOR_TEXT,
    EvolutionView,
    PeriodChosen,
    plural,
)

COLOR_BG = "#1a1b26"
COLOR_CURSOR_BG = "#283457"

GUTTER = 7
# Rows below the chart: axis labels, tags, blank, status
FOOTER_ROWS = 4
# Widest column a single period gets when history is short
MAX_COLUMN_WIDTH = 4


def compact(n: int) -> str:
    """Short number for the axis gutter: 950, 1.2k, 3.4M."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"


class FrequencyView(EvolutionView):
    """
    Lines added (up, green) and deleted (down, red) per week, month, or year.

    The granularity is the finest one that fits the width. h/l move the cursor,
    0/$ jump to the ends, Enter lists the period's commits.
    """

    BINDINGS = [
        ("h", "move(-1)", "Prev period"),
        ("l", "move(1)", "Next period"),
        ("left", "move(-1)", "Prev period"),
        ("right", "move(1)", "Next period"),
        ("0", "jump_first", "First"),
        ("$", "jump_last", "Last"),
        ("enter", "choose", "Commits"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cursor_date: date | None = None
        self.granularity: Granularity = "week"
        self._periods: list[PeriodStats] = []
        self._cap = 1
        self._layout_key: tuple[int, int] | None = None

    def on_data_changed(self) -> None:
        self._layout_key = None
        self._periods = []
        self.cursor_date = max(local_day(c.date, self.tz) for c in self.commits) if self.commits else None

    # Layout

    @property
    def chart_width(self) -> int:
        return max(1, self.size.width - GUTTER)

    @property
    def periods(self) -> list[PeriodStats]:
        """Periods for the current width (re-binned when the width changes)."""
        key = (self.chart_width, len(self.commits))
        if key != self._layout_key and self.commits:
            days = [local_day(c.date, self.tz) for c in self.commits]
            self.granularity = choose_granularity(min(days), max(days), self.chart_width)
            self._periods = bin_periods(self.commits, self.granularity, self.tz)
            self._cap = percentile_cap(
                [p.additions for p in self._periods] + [p.deletions for p in self._periods]
            )
            self._layout_key = key
        return self._periods

    @property
    def column_width(self) -> int:
        n = len(self.periods)
        return max(1, min(MAX_COLUMN_WIDTH, self.chart_width // n)) if n else 1

    @property
    def cursor(self) -> int:
        """Index of the period containing cursor_date."""
        periods = self.periods
        if not periods or self.cursor_date is None:
            return 0
        start = period_start(self.cursor_date, self.granularity)
        for i, p in enumerate(periods):
            if p.start == start:
                return i
        return len(periods) - 1

    # Navigation

    def _set_cursor(self, idx: int) -> None:
        periods = self.periods
        if not periods:
            return
        idx = max(0, min(len(periods) - 1, idx))
        self.cursor_date = periods[idx].start
        self.refresh()

    def action_move(self, delta: int) -> None:
        self._set_cursor(self.cursor + delta)

    def action_jump_first(self) -> None:
        self._set_cursor(0)

    def action_jump_last(self) -> None:
        self._set_cursor(len(self.periods) - 1)

    def action_choose(self) -> None:
        periods = self.periods
        if not periods:
            return
        p = periods[self.cursor]
        self.post_message(
            PeriodChosen(p.start, next_period(p.start, self.granularity), period_label(p.start, self.granularity))
        )

    # Rendering

    def status_text(self) -> Text:
        periods = self.periods
        if not periods:
            return Text()
        p = periods[self.cursor]
        text = Text()
        text.append(period_label(p.start, self.granularity), style=f"bold {COLOR_TEXT}")
        text.append("  ·  ", style=COLOR_DIM)
        text.append(plural(p.commits, "commit"), style=COLOR_TEXT)
        text.append("  ·  ", style=COLOR_DIM)
        text.append(f"+{p.additions:,}", style=COLOR_GREEN)
        text.append(f" −{p.deletions:,}", style=COLOR_RED)
        end = next_period(p.start, self.granularity)
        return self._status_line(text, tags_between(self.tags, p.start, end, self.tz))

    def _bar_cell(self, value: int, k: int, rows: int, up: bool, highlighted: bool) -> tuple[str, str]:
        """Glyph and style for cell k (0 = next to the axis) of a bar."""
        full, rem, clipped = bar_cells(value, self._cap, rows)
        color = COLOR_GREEN if up else COLOR_RED
        bg = f" on {COLOR_CURSOR_BG}" if highlighted else ""
        if clipped and k == rows - 1:
            return "█", COLOR_AMBER + bg
        if k < full:
            return "█", color + bg
        if k == full and rem:
            if up:
                return UP_BLOCKS[rem], color + bg
            # Fill from the top: paint the lower part in the background color
            return UP_BLOCKS[8 - rem], f"{COLOR_CURSOR_BG if highlighted else COLOR_BG} on {color}"
        return " ", bg.strip()

    def render(self) -> Text:
        if self.message:
            return self._render_message(self.message)
        periods = self.periods
        if not periods:
            return self._render_message("No commits")
        if self._too_small():
            return self._render_message("Terminal too small")

        chart_rows = self.size.height - FOOTER_ROWS
        up_rows = (chart_rows - 1) // 2
        down_rows = chart_rows - 1 - up_rows
        cw = self.column_width
        bar_w = cw - 1 if cw >= 3 else cw
        cursor = self.cursor
        cap_label = compact(self._cap)

        def bar_row(k: int, rows: int, up: bool, gutter: str) -> Text:
            line = Text(f"{gutter:>{GUTTER - 1}} ", style=COLOR_DIM)
            for i, p in enumerate(periods):
                value = p.additions if up else p.deletions
                glyph, style = self._bar_cell(value, k, rows, up, i == cursor)
                line.append(glyph * bar_w, style=style)
                if cw > bar_w:
                    line.append(" " * (cw - bar_w), style=f"on {COLOR_CURSOR_BG}" if i == cursor else "")
            return line

        text = Text()
        for r in range(up_rows):
            text.append_text(bar_row(up_rows - 1 - r, up_rows, True, f"+{cap_label}" if r == 0 else ""))
            text.append("\n")

        text.append(f"{'0':>{GUTTER - 1}} ", style=COLOR_DIM)
        for i in range(len(periods)):
            style = f"{COLOR_DIM} on {COLOR_CURSOR_BG}" if i == cursor else COLOR_DIM
            text.append("─" * cw, style=style)
        text.append("\n")

        for r in range(down_rows):
            text.append_text(bar_row(r, down_rows, False, f"−{cap_label}" if r == down_rows - 1 else ""))
            text.append("\n")

        starts = [p.start for p in periods]
        width = len(periods) * cw
        labels = [(i * cw, name) for i, name in axis_labels(starts, self.granularity)]
        text.append(" " * GUTTER + place_labels(labels, width) + "\n", style=COLOR_DIM)

        tag_cols = []
        index_by_start = {s: i for i, s in enumerate(starts)}
        for tag in self.tags:
            i = index_by_start.get(period_start(local_day(tag.date, self.tz), self.granularity))
            if i is not None:
                tag_cols.append((i * cw, tag.name))
        text.append(" " * GUTTER + place_labels(tag_cols, width, marker="▲") + "\n", style=COLOR_PURPLE)

        text.append("\n")
        text.append_text(self.status_text())
        return text
