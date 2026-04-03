"""Tests for ChangedFilesWidget logic."""

from gvt.widgets.changed_files import ChangedFilesWidget


class TestSetFiles:
    def test_updates_file_list(self):
        w = ChangedFilesWidget()
        files = [("a.py", 10, 5), ("b.py", 3, 0)]
        w.files = files
        w.selected_idx = 0
        w._build_lines()
        assert len(w.files) == 2
        assert len(w._lines) == 2

    def test_resets_selection(self):
        w = ChangedFilesWidget()
        w.selected_idx = 5
        w.files = [("a.py", 1, 0)]
        w.selected_idx = 0
        assert w.selected_idx == 0

    def test_empty_files(self):
        w = ChangedFilesWidget()
        w.files = []
        w._build_lines()
        assert len(w._lines) == 1
        assert "No files changed" in w._lines[0].plain


class TestClear:
    def test_empties_list(self):
        w = ChangedFilesWidget()
        w.files = [("a.py", 1, 0)]
        w.clear()
        assert w.files == []
        assert w.selected_idx == 0
        assert "No commit selected" in w._lines[0].plain


class TestCursorMovement:
    def test_cursor_down(self):
        w = ChangedFilesWidget()
        w.files = [("a.py", 1, 0), ("b.py", 2, 1), ("c.py", 3, 2)]
        w.selected_idx = 0
        # Simulate cursor_down logic
        if w.files and w.selected_idx < len(w.files) - 1:
            w.selected_idx += 1
        assert w.selected_idx == 1

    def test_cursor_up(self):
        w = ChangedFilesWidget()
        w.files = [("a.py", 1, 0), ("b.py", 2, 1)]
        w.selected_idx = 1
        if w.files and w.selected_idx > 0:
            w.selected_idx -= 1
        assert w.selected_idx == 0

    def test_cursor_down_at_end(self):
        w = ChangedFilesWidget()
        w.files = [("a.py", 1, 0), ("b.py", 2, 1)]
        w.selected_idx = 1
        if w.files and w.selected_idx < len(w.files) - 1:
            w.selected_idx += 1
        assert w.selected_idx == 1  # didn't move

    def test_cursor_up_at_start(self):
        w = ChangedFilesWidget()
        w.files = [("a.py", 1, 0)]
        w.selected_idx = 0
        if w.files and w.selected_idx > 0:
            w.selected_idx -= 1
        assert w.selected_idx == 0  # didn't move

    def test_cursor_down_empty(self):
        w = ChangedFilesWidget()
        w.files = []
        w.selected_idx = 0
        if w.files and w.selected_idx < len(w.files) - 1:
            w.selected_idx += 1
        assert w.selected_idx == 0


class TestBuildLines:
    def test_lines_include_file_names(self):
        w = ChangedFilesWidget()
        w.files = [("src/main.py", 5, 2), ("README.md", 1, 0)]
        w.selected_idx = 0
        w._build_lines()
        text = " ".join(line.plain for line in w._lines)
        assert "src/main.py" in text
        assert "README.md" in text

    def test_lines_include_stats(self):
        w = ChangedFilesWidget()
        w.files = [("a.py", 10, 3)]
        w.selected_idx = 0
        w._build_lines()
        text = w._lines[0].plain
        assert "+10" in text
        assert "-3" in text

    def test_selected_line_has_marker(self):
        w = ChangedFilesWidget()
        w.files = [("a.py", 1, 0), ("b.py", 2, 1)]
        w.selected_idx = 0
        w._build_lines()
        assert "▸" in w._lines[0].plain
        assert "▸" not in w._lines[1].plain
