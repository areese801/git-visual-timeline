"""
Hotspots for the Evolution screen: the files that change most often, with
recent commits counting more.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Callable

from rich.cells import cell_len
from rich.text import Text

from gvt.evolution import Hotspot, age_label, hbar, hotspot_half_life, local_day, rank_hotspots
from gvt.textsafe import safe_name
from gvt.widgets.evolution_common import (
    COLOR_AMBER,
    COLOR_DIM,
    COLOR_GREEN,
    COLOR_RED,
    COLOR_TEXT,
    EvolutionView,
    FileChosen,
    format_count,
    plural,
)
from gvt.widgets.frequency_view import compact

COLOR_ROW_CURSOR = "#283457"

FILE_SCOPE_MESSAGE = "Hotspots rank the files in a folder; press u to widen"
NO_FILES_MESSAGE = "No tracked files changed"

# Widths of the columns after the path, in drawing order, and the space between them
COLUMN_WIDTHS = {"bar": 12, "commits": 14, "lines": 15, "age": 8}
GAP = 2
# Narrowest path column before optional columns are dropped
MIN_PATH = 20
# Optional columns, in the order they're dropped on narrow terminals
DROP_ORDER = ("age", "lines", "bar")
# Rows below the list: blank, status
FOOTER_ROWS = 2
# Narrowest path in the status line before "last changed" is dropped
MIN_STATUS_PATH = 10


def fit_columns(width: int, rank_width: int) -> tuple[int, list[str]]:
    """
    Columns to draw after the path, and the path's width, for rows `width`
    cells wide.

    Optional columns are dropped (age, then lines, then the bar) until the path
    gets at least MIN_PATH cells; the commit count always stays.
    """
    columns = list(COLUMN_WIDTHS)

    def path_width() -> int:
        return width - rank_width - sum(COLUMN_WIDTHS[c] + GAP for c in columns)

    for column in DROP_ORDER:
        if path_width() >= MIN_PATH:
            break
        columns.remove(column)
    return max(1, path_width()), columns


def shorten_left(name: str, width: int) -> str:
    """
    `name` cut from the left with '…' so it fits `width` cells.
    """
    if cell_len(name) <= width:
        return name
    budget, used, start = width - 1, 0, len(name)
    while start > 0 and used + cell_len(name[start - 1]) <= budget:
        used += cell_len(name[start - 1])
        start -= 1
    return "…" + name[start:]


class HotspotsView(EvolutionView):
    """
    Files under the scope ranked by recency-weighted commit count.

    j/k move, g/G jump to the ends, PgUp/PgDn page, Enter opens the file.
    """

    BINDINGS = [
        ("j", "move(1)", "Next file"),
        ("k", "move(-1)", "Prev file"),
        ("down", "move(1)", "Next file"),
        ("up", "move(-1)", "Prev file"),
        ("pagedown", "page(1)", "Page down"),
        ("pageup", "page(-1)", "Page up"),
        ("g", "ends(0)", "First file"),
        ("G", "ends(1)", "Last file"),
        ("home", "ends(0)", "First file"),
        ("end", "ends(1)", "Last file"),
        ("enter", "choose", "Open file"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.hotspots: list[Hotspot] = []
        self.cursor = 0
        # Index of the first row shown
        self.top = 0
        self.half_life = 0.0
        # Cells in the longest path, so the path column never outgrows the data
        self.longest_path = 0
        # Set by the screen before set_data(): which paths count, whether the
        # scope is a single file, and the first day of the history shown
        self.keep: Callable[[str], bool] = lambda path: True
        self.scope_is_file = False
        self.history_start: date | None = None
        # Day that ages are measured to; None means today (tests pin it)
        self.today: date | None = None

    def _today(self) -> date:
        return self.today or datetime.now(self.tz).date()

    def on_data_changed(self) -> None:
        self.cursor = self.top = 0
        self.hotspots = []
        self.longest_path = 0
        if self.scope_is_file:
            self.message = FILE_SCOPE_MESSAGE
            return
        if not self.commits:
            return
        today = self._today()
        start = self.history_start or min(local_day(c.date, self.tz) for c in self.commits)
        self.half_life = hotspot_half_life(start, today)
        self.hotspots = rank_hotspots(self.commits, today, self.half_life, self.keep, self.tz)
        if not self.hotspots:
            self.message = NO_FILES_MESSAGE
        else:
            self.longest_path = max(cell_len(safe_name(s.path)) for s in self.hotspots)

    # Navigation

    def _rows(self) -> int:
        return max(1, self.size.height - FOOTER_ROWS)

    def _scroll_to_cursor(self) -> None:
        """
        Shift the list just enough to keep the cursor visible.
        """
        rows = self._rows()
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + rows:
            self.top = self.cursor - rows + 1

    def on_resize(self) -> None:
        self._scroll_to_cursor()
        # A taller terminal shouldn't leave blank rows below a long list
        self.top = max(0, min(self.top, len(self.hotspots) - self._rows()))

    def _go(self, index: int) -> None:
        if not self.hotspots:
            return
        self.cursor = max(0, min(len(self.hotspots) - 1, index))
        self._scroll_to_cursor()
        self.refresh()

    def action_move(self, step: int) -> None:
        self._go(self.cursor + step)

    def action_page(self, direction: int) -> None:
        self._go(self.cursor + direction * self._rows())

    def action_ends(self, end: int) -> None:
        self._go(len(self.hotspots) - 1 if end else 0)

    def action_choose(self) -> None:
        if self.hotspots:
            self.post_message(FileChosen(self.hotspots[self.cursor].path))

    # Rendering

    def status_text(self) -> Text:
        if not self.hotspots:
            return Text()
        spot = self.hotspots[self.cursor]
        counts = (
            f"{plural(spot.commits, 'commit')}, {format_count(spot.recent_commits)} "
            f"in the last {round(self.half_life)} days"
        )
        changed = f"last changed {local_day(spot.last_change, self.tz).isoformat()}"
        separator = "  ·  "
        # Build the tail first, then give the path whatever width is left
        tail = cell_len(separator) * 2 + cell_len(counts) + cell_len(changed)
        show_changed = self.size.width - tail >= MIN_STATUS_PATH
        if not show_changed:
            tail -= cell_len(separator) + cell_len(changed)
        path_width = max(1, self.size.width - tail)
        text = Text()
        text.append(shorten_left(safe_name(spot.path), path_width), style=f"bold {COLOR_TEXT}")
        text.append(separator, style=COLOR_DIM)
        text.append(counts, style=COLOR_TEXT)
        if show_changed:
            text.append(separator, style=COLOR_DIM)
            text.append(changed, style=COLOR_TEXT)
        return text

    def _append_cell(self, text: Text, column: str, spot: Hotspot, top_score: float, today: date) -> None:
        width = COLUMN_WIDTHS[column]
        if column == "bar":
            text.append(hbar(spot.score / top_score if top_score else 0.0, width), style=COLOR_AMBER)
        elif column == "commits":
            text.append(plural(spot.commits, "commit").rjust(width), style=COLOR_TEXT)
        elif column == "lines":
            added, deleted = f"+{compact(spot.additions)}", f" −{compact(spot.deletions)}"
            text.append(" " * max(0, width - len(added) - len(deleted)))
            text.append(added, style=COLOR_GREEN)
            text.append(deleted, style=COLOR_RED)
        else:
            text.append(age_label(local_day(spot.last_change, self.tz), today).rjust(width), style=COLOR_DIM)

    def render(self) -> Text:
        if self.message:
            return self._render_message(self.message)
        if not self.hotspots:
            return self._render_message("No commits")
        if self._too_small():
            return self._render_message("Terminal too small")

        rank_width = len(str(len(self.hotspots))) + 2
        path_width, columns = fit_columns(self.size.width, rank_width)
        path_width = max(1, min(path_width, self.longest_path))
        top_score = self.hotspots[0].score
        today = self._today()
        rows = self._rows()
        shown = self.hotspots[self.top : self.top + rows]

        text = Text()
        for index, spot in enumerate(shown, start=self.top):
            start = len(text)
            text.append(f"{index + 1:>{rank_width - 1}} ", style=COLOR_DIM)
            name = shorten_left(safe_name(spot.path), path_width)
            text.append(name + " " * (path_width - cell_len(name)), style=COLOR_TEXT)
            for column in columns:
                text.append(" " * GAP)
                self._append_cell(text, column, spot, top_score, today)
            if index == self.cursor:
                text.append(" " * max(0, self.size.width - cell_len(text.plain[start:])))
                text.stylize(f"bold on {COLOR_ROW_CURSOR}", start, len(text))
            text.append("\n")
        # Blank rows below a short list, then a spacer, then the status line
        text.append("\n" * (rows - len(shown) + 1))
        text.append_text(self.status_text())
        return text
