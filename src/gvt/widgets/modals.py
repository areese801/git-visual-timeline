"""Modal widgets for gvt: commit search, file search, commit detail."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, Label, Static
from rich.text import Text

from gvt.git.repo import CommitInfo

try:
    from thefuzz import fuzz
except ImportError:
    fuzz = None


# Colors
COLOR_ACCENT = "#7aa2f7"
COLOR_PURPLE = "#bb9af7"
COLOR_DIM = "#565f89"
COLOR_TEXT = "#c0caf5"
COLOR_GREEN = "#9ece6a"
COLOR_RED = "#f7768e"
COLOR_AMBER = "#e0af68"
COLOR_SELECTED_BG = "#283457"
COLOR_BG = "#1a1b26"


class CommitSelected(Message):
    """A commit was selected from search."""

    def __init__(self, commit_index: int, cursor: str = "left") -> None:
        self.commit_index = commit_index
        self.cursor = cursor
        super().__init__()


class FileSearchSelected(Message):
    """A file was selected from file search."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__()


class CommitSearchModal(ModalScreen):
    """Fuzzy search over commit messages."""

    DEFAULT_CSS = """
    CommitSearchModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #commit-search-container {
        width: 70%;
        height: 70%;
        background: #1a1b26;
        border: solid #7aa2f7;
        padding: 1 2;
    }

    #commit-search-input {
        background: #24283b;
        color: #c0caf5;
        border: solid #3b4261;
        margin-bottom: 1;
    }

    #commit-search-input:focus {
        border: solid #7aa2f7;
    }

    #commit-search-results {
        height: 1fr;
        overflow-y: auto;
        background: #1a1b26;
    }
    """

    BINDINGS = [
        ("escape", "dismiss_modal", "Close"),
    ]

    def __init__(self, commits: list[CommitInfo], **kwargs) -> None:
        super().__init__(**kwargs)
        self.commits = commits
        self.filtered: list[tuple[int, CommitInfo]] = [(i, c) for i, c in enumerate(commits)]
        self.selected_idx = 0

    def compose(self) -> ComposeResult:
        with Container(id="commit-search-container"):
            yield Label("Search Commits (type to filter, Tab/Shift+Tab to navigate, Enter to select)", id="commit-search-title")
            yield Input(placeholder="Search commit messages...", id="commit-search-input")
            yield Vertical(id="commit-search-results")

    def on_mount(self) -> None:
        self.query_one("#commit-search-input", Input).focus()
        self._update_results()

    @on(Input.Changed, "#commit-search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        query = event.value.strip()
        if not query:
            self.filtered = [(i, c) for i, c in enumerate(self.commits)]
        else:
            scored = []
            query_lower = query.lower()
            for i, commit in enumerate(self.commits):
                search_text = commit.searchable_text.lower()
                # Prefer direct substring match, fall back to fuzzy
                if query_lower in search_text:
                    score = 100
                elif fuzz:
                    score = fuzz.partial_ratio(query_lower, search_text)
                else:
                    score = 0
                if score > 65:
                    scored.append((score, i, commit))
            scored.sort(key=lambda x: x[0], reverse=True)
            self.filtered = [(i, c) for _, i, c in scored]

        self.selected_idx = 0
        self._update_results()

    def _update_results(self) -> None:
        results = self.query_one("#commit-search-results", Vertical)
        results.remove_children()

        for display_idx, (commit_idx, commit) in enumerate(self.filtered[:50]):
            line = Text()
            is_selected = display_idx == self.selected_idx

            if is_selected:
                line.append("▸ ", style=f"bold {COLOR_ACCENT}")
            else:
                line.append("  ")

            line.append(commit.short_hash, style=f"bold {COLOR_ACCENT}")
            line.append("  ", style="")
            line.append(commit.date.strftime("%Y-%m-%d"), style=COLOR_DIM)
            line.append("  ", style="")
            line.append(commit.first_line[:60], style=COLOR_TEXT)
            line.append(f"  +{commit.additions} -{commit.deletions}", style=COLOR_DIM)

            label = Static(line)
            if is_selected:
                label.styles.background = COLOR_SELECTED_BG
            results.mount(label)

    def on_key(self, event) -> None:
        input_focused = self.query_one("#commit-search-input", Input).has_focus
        if event.key == "down" or event.key == "ctrl+n" or event.key == "tab" or (event.key == "j" and not input_focused):
            self.selected_idx = min(self.selected_idx + 1, len(self.filtered) - 1)
            self._update_results()
            event.prevent_default()
        elif event.key == "up" or event.key == "ctrl+p" or event.key == "shift+tab" or (event.key == "k" and not input_focused):
            self.selected_idx = max(self.selected_idx - 1, 0)
            self._update_results()
            event.prevent_default()
        elif event.key == "enter":
            if self.filtered:
                commit_idx, _ = self.filtered[self.selected_idx]
                self.dismiss(("select", commit_idx))
            event.prevent_default()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


class FileSearchModal(ModalScreen):
    """Fuzzy search over tracked files."""

    DEFAULT_CSS = """
    FileSearchModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #file-search-container {
        width: 70%;
        height: 70%;
        background: #1a1b26;
        border: solid #7aa2f7;
        padding: 1 2;
    }

    #file-search-input {
        background: #24283b;
        color: #c0caf5;
        border: solid #3b4261;
        margin-bottom: 1;
    }

    #file-search-input:focus {
        border: solid #7aa2f7;
    }

    #file-search-results {
        height: 1fr;
        overflow-y: auto;
        background: #1a1b26;
    }
    """

    BINDINGS = [
        ("escape", "dismiss_modal", "Close"),
    ]

    def __init__(self, files: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self.files = files
        self.filtered: list[str] = list(files)
        self.selected_idx = 0

    def compose(self) -> ComposeResult:
        with Container(id="file-search-container"):
            yield Label("Search Files (type to filter, Tab/Shift+Tab to navigate, Enter to select)", id="file-search-title")
            yield Input(placeholder="Search files...", id="file-search-input")
            yield Vertical(id="file-search-results")

    def on_mount(self) -> None:
        self.query_one("#file-search-input", Input).focus()
        self._update_results()

    @on(Input.Changed, "#file-search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        query = event.value.strip()
        if not query:
            self.filtered = list(self.files)
        else:
            scored = []
            query_lower = query.lower()
            for f in self.files:
                f_lower = f.lower()
                if query_lower in f_lower:
                    score = 100
                elif fuzz:
                    score = fuzz.partial_ratio(query_lower, f_lower)
                else:
                    score = 0
                if score > 65:
                    scored.append((score, f))
            scored.sort(key=lambda x: x[0], reverse=True)
            self.filtered = [f for _, f in scored]

        self.selected_idx = 0
        self._update_results()

    def _update_results(self) -> None:
        results = self.query_one("#file-search-results", Vertical)
        results.remove_children()

        for display_idx, file_path in enumerate(self.filtered[:50]):
            line = Text()
            is_selected = display_idx == self.selected_idx

            if is_selected:
                line.append("▸ ", style=f"bold {COLOR_ACCENT}")
            else:
                line.append("  ")

            line.append(file_path, style=COLOR_TEXT)

            label = Static(line)
            if is_selected:
                label.styles.background = COLOR_SELECTED_BG
            results.mount(label)

    def on_key(self, event) -> None:
        input_focused = self.query_one("#file-search-input", Input).has_focus
        if event.key == "down" or event.key == "ctrl+n" or event.key == "tab" or (event.key == "j" and not input_focused):
            self.selected_idx = min(self.selected_idx + 1, len(self.filtered) - 1)
            self._update_results()
            event.prevent_default()
        elif event.key == "up" or event.key == "ctrl+p" or event.key == "shift+tab" or (event.key == "k" and not input_focused):
            self.selected_idx = max(self.selected_idx - 1, 0)
            self._update_results()
            event.prevent_default()
        elif event.key == "enter":
            if self.filtered:
                self.dismiss(self.filtered[self.selected_idx])
            event.prevent_default()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


class CommitDetailPopup(ModalScreen):
    """Full commit detail popup."""

    DEFAULT_CSS = """
    CommitDetailPopup {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #commit-detail-container {
        width: 60%;
        height: 50%;
        background: #1a1b26;
        border: solid #7aa2f7;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        ("escape", "dismiss_modal", "Close"),
        ("enter", "dismiss_modal", "Close"),
        ("q", "dismiss_modal", "Close"),
    ]

    def __init__(self, commit: CommitInfo, **kwargs) -> None:
        super().__init__(**kwargs)
        self.commit = commit

    def compose(self) -> ComposeResult:
        c = self.commit
        text = Text()
        text.append("Commit Detail\n\n", style=f"bold {COLOR_ACCENT}")
        text.append("Hash:   ", style=f"bold {COLOR_DIM}")
        text.append(f"{c.hexsha}\n", style=COLOR_ACCENT)
        text.append("Author: ", style=f"bold {COLOR_DIM}")
        text.append(f"{c.author}\n", style=COLOR_TEXT)
        text.append("Date:   ", style=f"bold {COLOR_DIM}")
        text.append(f"{c.date.strftime('%Y-%m-%d %H:%M:%S %Z')}\n", style=COLOR_TEXT)
        text.append("Stats:  ", style=f"bold {COLOR_DIM}")
        text.append(f"+{c.additions}", style=COLOR_GREEN)
        text.append(f" -{c.deletions}\n\n", style=COLOR_RED)
        text.append("Message:\n", style=f"bold {COLOR_DIM}")
        text.append(c.message, style=COLOR_TEXT)

        with Container(id="commit-detail-container"):
            yield Static(text)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


class CommitFilesModal(ModalScreen):
    """Shows all files changed in a commit, allows selecting one."""

    DEFAULT_CSS = """
    CommitFilesModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #commit-files-container {
        width: 70%;
        height: 70%;
        background: #1a1b26;
        border: solid #7aa2f7;
        padding: 1 2;
    }

    #commit-files-results {
        height: 1fr;
        overflow-y: auto;
        background: #1a1b26;
    }
    """

    BINDINGS = [
        ("escape", "dismiss_modal", "Close"),
        ("q", "dismiss_modal", "Close"),
    ]

    def __init__(
        self,
        commit: CommitInfo,
        files: list[tuple[str, int, int]],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.commit = commit
        self.files = files
        self.selected_idx = 0

    def compose(self) -> ComposeResult:
        c = self.commit
        header = Text()
        header.append(f"Files changed in ", style=COLOR_DIM)
        header.append(f"{c.short_hash}", style=f"bold {COLOR_ACCENT}")
        header.append(f"  {c.first_line}", style=COLOR_TEXT)
        header.append(f"  ({len(self.files)} files)", style=COLOR_DIM)

        with Container(id="commit-files-container"):
            yield Static(header)
            yield Vertical(id="commit-files-results")

    def on_mount(self) -> None:
        self._update_results()

    def _update_results(self) -> None:
        results = self.query_one("#commit-files-results", Vertical)
        results.remove_children()

        for idx, (file_path, adds, dels) in enumerate(self.files):
            line = Text()
            is_selected = idx == self.selected_idx

            if is_selected:
                line.append("▸ ", style=f"bold {COLOR_ACCENT}")
            else:
                line.append("  ")

            line.append(file_path, style=COLOR_TEXT if not is_selected else f"bold {COLOR_TEXT}")
            line.append("  ", style="")
            line.append(f"+{adds}", style=COLOR_GREEN)
            line.append(f" -{dels}", style=COLOR_RED)

            label = Static(line)
            if is_selected:
                label.styles.background = COLOR_SELECTED_BG
            results.mount(label)

    def on_key(self, event) -> None:
        if event.key == "down" or event.key == "j" or event.key == "ctrl+n" or event.key == "tab":
            self.selected_idx = min(self.selected_idx + 1, len(self.files) - 1)
            self._update_results()
            event.prevent_default()
        elif event.key == "up" or event.key == "k" or event.key == "ctrl+p" or event.key == "shift+tab":
            self.selected_idx = max(self.selected_idx - 1, 0)
            self._update_results()
            event.prevent_default()
        elif event.key == "enter":
            if self.files:
                file_path, _, _ = self.files[self.selected_idx]
                self.dismiss(file_path)
            event.prevent_default()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


class QuitConfirmModal(ModalScreen):
    """Simple y/n quit confirmation."""

    DEFAULT_CSS = """
    QuitConfirmModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #quit-confirm-container {
        width: 50;
        height: 5;
        background: #1a1b26;
        border: solid #f7768e;
        padding: 1 2;
        content-align: center middle;
    }
    """

    BINDINGS = [
        ("y", "confirm_yes", "Yes"),
        ("n", "confirm_no", "No"),
        ("escape", "confirm_no", "No"),
    ]

    def compose(self) -> ComposeResult:
        text = Text()
        text.append("Quit Git Visual Timeline? ", style=f"bold {COLOR_TEXT}")
        text.append("y", style=f"bold {COLOR_GREEN}")
        text.append("/", style=COLOR_DIM)
        text.append("n", style=f"bold {COLOR_RED}")

        with Container(id="quit-confirm-container"):
            yield Static(text)

    def action_confirm_yes(self) -> None:
        self.dismiss(True)

    def action_confirm_no(self) -> None:
        self.dismiss(False)


class TimeFilterModal(ModalScreen):
    """Pick a time range to filter the timeline."""

    PRESETS = [
        ("1w", "Last week"),
        ("1m", "Last month"),
        ("3m", "Last 3 months"),
        ("6m", "Last 6 months"),
        ("1y", "Last year"),
        ("", "All time"),
    ]

    DEFAULT_CSS = """
    TimeFilterModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }

    #time-filter-container {
        width: 50;
        height: auto;
        max-height: 16;
        background: #1a1b26;
        border: solid #7aa2f7;
        padding: 1 2;
    }

    #time-filter-input {
        background: #24283b;
        color: #c0caf5;
        border: solid #3b4261;
        margin-top: 1;
    }

    #time-filter-input:focus {
        border: solid #7aa2f7;
    }
    """

    BINDINGS = [
        ("escape", "dismiss_modal", "Close"),
    ]

    def __init__(self, current_filter: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.current_filter = current_filter
        self.selected_idx = 0
        # Find current preset index
        for i, (value, _) in enumerate(self.PRESETS):
            if value == current_filter:
                self.selected_idx = i
                break

    def compose(self) -> ComposeResult:
        with Container(id="time-filter-container"):
            yield Static(Text("Filter Timeline Since", style=f"bold {COLOR_ACCENT}"))

            results = Vertical(id="time-filter-results")
            yield results

            yield Static(Text("\nCustom date:", style=COLOR_DIM))
            yield Input(placeholder="YYYY-MM-DD or 3m, 6w, 1y...", id="time-filter-input")

    def on_mount(self) -> None:
        self._update_presets()

    def _update_presets(self) -> None:
        results = self.query_one("#time-filter-results", Vertical)
        results.remove_children()
        for idx, (value, label) in enumerate(self.PRESETS):
            line = Text()
            is_selected = idx == self.selected_idx
            is_active = value == self.current_filter

            if is_selected:
                line.append("▸ ", style=f"bold {COLOR_ACCENT}")
            elif is_active:
                line.append("● ", style=f"bold {COLOR_GREEN}")
            else:
                line.append("  ")

            line.append(label, style=COLOR_TEXT if not is_active else f"bold {COLOR_GREEN}")
            if value:
                line.append(f"  ({value})", style=COLOR_DIM)

            static = Static(line)
            if is_selected:
                static.styles.background = COLOR_SELECTED_BG
            results.mount(static)

    def on_key(self, event) -> None:
        if event.key == "down" or event.key == "j" or event.key == "ctrl+n" or event.key == "tab":
            self.selected_idx = min(self.selected_idx + 1, len(self.PRESETS) - 1)
            self._update_presets()
            event.prevent_default()
        elif event.key == "up" or event.key == "k" or event.key == "ctrl+p" or event.key == "shift+tab":
            self.selected_idx = max(self.selected_idx - 1, 0)
            self._update_presets()
            event.prevent_default()
        elif event.key == "enter":
            # Check if input has focus
            input_widget = self.query_one("#time-filter-input", Input)
            if input_widget.has_focus and input_widget.value.strip():
                self.dismiss(input_widget.value.strip())
            else:
                value, _ = self.PRESETS[self.selected_idx]
                self.dismiss(value)
            event.prevent_default()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


class HelpModal(ModalScreen):
    """Help overlay showing keybindings."""

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #help-container {
        width: 60%;
        height: 70%;
        background: #1a1b26;
        border: solid #7aa2f7;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        ("escape", "dismiss_modal", "Close"),
        ("question_mark", "dismiss_modal", "Close"),
        ("q", "dismiss_modal", "Close"),
    ]

    def compose(self) -> ComposeResult:
        text = Text()
        text.append("gvt — Git Visual Timeline\n\n", style=f"bold {COLOR_ACCENT}")

        sections = [
            ("Global", [
                ("1-5", "Jump to pane"),
                ("Ctrl+h/j/k/l", "Navigate panes directionally"),
                ("Tab/Shift+Tab", "Cycle panes"),
                ("c", "Commit search"),
                ("f / Ctrl+P", "File search"),
                ("?", "This help"),
                ("y/Y", "Copy short/full commit hash"),
                ("e", "Open file in $EDITOR"),
                ("q / Esc", "Quit"),
            ]),
            ("File Tree [1]", [
                ("j/k/↑/↓", "Navigate"),
                ("Enter", "Select file → focus timeline"),
                ("o", "Expand/collapse"),
            ]),
            ("Timeline [2]", [
                ("h/l/←/→", "Move cursor"),
                ("0/$", "Jump to first/last"),
                ("x", "Pin commit (1st=start, 2nd=end, 3rd=clear)"),
                ("X", "Snap nearest pin to cursor"),
                ("t", "Time filter (since date)"),
                ("Esc", "Clear pins"),
            ]),
            ("Commits [3]", [
                ("j/k/↑/↓", "Toggle focus row"),
                ("Enter/m", "Show full commit"),
            ]),
            ("Diff [4]", [
                ("j/k/↑/↓", "Scroll"),
                ("g/G", "Top/bottom"),
                ("n/p", "Next/prev hunk"),
                ("+/- or m/l", "More/less context lines"),
                ("w", "Toggle whole file view"),
                ("d", "Toggle side-by-side diff"),
                ("b", "Toggle inline blame"),
                ("/", "Search in diff"),
            ]),
            ("Changed Files [5]", [
                ("j/k/↑/↓", "Navigate"),
                ("Enter", "Open file timeline"),
            ]),
        ]

        for title, bindings in sections:
            text.append(f"  {title}\n", style=f"bold {COLOR_AMBER}")
            for key, desc in bindings:
                text.append(f"    {key:<20}", style=f"bold {COLOR_ACCENT}")
                text.append(f"{desc}\n", style=COLOR_TEXT)
            text.append("\n")

        with Container(id="help-container"):
            yield Static(text)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)
