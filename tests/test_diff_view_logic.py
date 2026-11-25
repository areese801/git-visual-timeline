"""Tests for DiffViewWidget logic (no rendering required)."""

from gvt.widgets.diff_view import DiffViewWidget, MODE_DIFF, MODE_FULL


SAMPLE_DIFF = """\
@@ -1,3 +1,4 @@
 print('hello')
-print('old')
+print('new')
+print('added')
 print('end')"""

MULTI_HUNK_DIFF = """\
@@ -1,3 +1,3 @@
 line1
-old1
+new1
 line3
@@ -10,3 +10,4 @@
 line10
-old10
+new10
+added10
 line12"""


class TestParseDiff:
    def test_line_count(self):
        dv = DiffViewWidget()
        dv._parse_diff(SAMPLE_DIFF)
        # One line per line of diff text (including @@ header, context, +, -)
        assert len(dv._lines) == len(SAMPLE_DIFF.split("\n"))

    def test_hunk_positions(self):
        dv = DiffViewWidget()
        dv._parse_diff(SAMPLE_DIFF)
        # One @@ line at position 0
        assert 0 in dv._hunk_positions

    def test_multi_hunk_positions(self):
        dv = DiffViewWidget()
        dv._parse_diff(MULTI_HUNK_DIFF)
        assert len(dv._hunk_positions) == 2

    def test_diff_line_to_file_line_mapping(self):
        dv = DiffViewWidget()
        dv._parse_diff(SAMPLE_DIFF)
        # Added and context lines should be mapped
        assert len(dv._diff_line_to_file_line) > 0

    def test_empty_diff(self):
        dv = DiffViewWidget()
        dv._parse_diff("")
        assert len(dv._lines) == 1
        assert "No diff" in dv._lines[0].plain


class TestParseDiffLineNumbers:
    def test_add_lines_detected(self):
        dv = DiffViewWidget()
        dv._parse_diff_line_numbers(SAMPLE_DIFF)
        # "+print('new')" is at new file line 2, "+print('added')" at line 3
        assert 2 in dv._full_file_add_lines
        assert 3 in dv._full_file_add_lines

    def test_del_lines_detected(self):
        dv = DiffViewWidget()
        dv._parse_diff_line_numbers(SAMPLE_DIFF)
        assert len(dv._full_file_del_lines) > 0

    def test_empty_diff_no_lines(self):
        dv = DiffViewWidget()
        dv._parse_diff_line_numbers("")
        assert len(dv._full_file_add_lines) == 0
        assert len(dv._full_file_del_lines) == 0


class TestContextLines:
    def test_default_context(self):
        dv = DiffViewWidget()
        assert dv.context_lines == 3

    def test_more_context(self):
        dv = DiffViewWidget()
        dv.context_lines = 3
        dv.action_more_context()
        assert dv.context_lines == 6

    def test_less_context(self):
        dv = DiffViewWidget()
        dv.context_lines = 3
        dv.action_less_context()
        assert dv.context_lines == 0

    def test_less_context_min_zero(self):
        dv = DiffViewWidget()
        dv.context_lines = 1
        dv.action_less_context()
        assert dv.context_lines == 0


class TestViewMode:
    def test_starts_as_diff(self):
        dv = DiffViewWidget()
        assert dv.view_mode == MODE_DIFF

class TestBlame:
    def test_blame_default_disabled(self):
        dv = DiffViewWidget()
        assert dv.blame_enabled is False

    def test_toggle_blame(self):
        dv = DiffViewWidget()
        dv.action_toggle_blame()
        assert dv.blame_enabled is True
        dv.action_toggle_blame()
        assert dv.blame_enabled is False

    def test_set_blame_stores_data(self):
        dv = DiffViewWidget()
        blame_data = [
            ("abc1234", "Alice", "2025-01-01"),
            ("def5678", "Bob", "2025-01-02"),
        ]
        dv.set_blame(blame_data)
        assert len(dv._blame_data) == 2

    def test_get_blame_for_full_file_mode(self):
        dv = DiffViewWidget()
        dv.view_mode = MODE_FULL
        dv.blame_enabled = True
        dv._blame_data = [
            ("abc1234", "Alice", "2025-01-01"),
            ("def5678", "Bob", "2025-01-02"),
        ]
        # line_idx 1 maps to file_line 0 (header is line 0)
        result = dv._get_blame_for_display_line(1)
        assert result is not None
        assert "abc1234" in result
        assert "Alice" in result

    def test_get_blame_header_line_returns_none(self):
        dv = DiffViewWidget()
        dv.view_mode = MODE_FULL
        dv.blame_enabled = True
        dv._blame_data = [("abc1234", "Alice", "2025-01-01")]
        result = dv._get_blame_for_display_line(0)
        assert result is None

    def test_get_blame_disabled_returns_none(self):
        dv = DiffViewWidget()
        dv.blame_enabled = False
        dv._blame_data = [("abc1234", "Alice", "2025-01-01")]
        result = dv._get_blame_for_display_line(1)
        assert result is None

    def test_get_blame_no_data_returns_none(self):
        dv = DiffViewWidget()
        dv.blame_enabled = True
        dv._blame_data = []
        result = dv._get_blame_for_display_line(1)
        assert result is None


class TestFlashLines:
    def test_flash_lines_start_empty(self):
        dv = DiffViewWidget()
        assert len(dv._flash_lines) == 0

    def test_flash_clears_highlight(self):
        dv = DiffViewWidget()
        dv._flash_lines = {0, 1, 2}
        dv._clear_flash()
        assert not dv._flash_lines


class TestSearch:
    def test_search_mode_default_off(self):
        dv = DiffViewWidget()
        assert dv._search_mode is False

    def test_search_query_default_empty(self):
        dv = DiffViewWidget()
        assert dv._search_query == ""

    def test_search_match_lines_default_empty(self):
        dv = DiffViewWidget()
        assert dv._search_match_lines == []

    def test_apply_search_finds_lines(self, monkeypatch):
        dv = DiffViewWidget()
        dv._parse_diff(SAMPLE_DIFF)
        monkeypatch.setattr(dv, "scroll_to", lambda **kwargs: None)
        dv._apply_search("NeW")
        assert dv._search_match_lines == [3]
        assert dv._search_highlight_lines == {3}
        assert dv._search_match_idx == 0
        dv._apply_search("")
        assert not dv._search_match_lines and dv._search_pattern is None

    def test_apply_search_invalid_regex(self):
        dv = DiffViewWidget()
        dv._parse_diff(SAMPLE_DIFF)
        dv._apply_search("[invalid")
        assert dv._search_pattern is None and not dv._search_match_lines

    def test_exit_search_clears_state(self):
        dv = DiffViewWidget()
        dv._search_mode = True
        dv._search_query = "test"
        dv._search_match_lines = [1, 2]
        dv._search_highlight_lines = {1, 2}
        dv._exit_search()
        assert dv._search_mode is False
        assert dv._search_query == ""
        assert len(dv._search_match_lines) == 0


class TestSetMessage:
    def test_set_message(self):
        dv = DiffViewWidget()
        dv._lines = []
        dv._hunk_positions = [1, 2]
        dv.set_message("hello world")
        assert len(dv._lines) == 1
        assert "hello world" in dv._lines[0].plain
        assert dv._hunk_positions == []


class TestSideBySide:
    def test_side_by_side_default_off(self):
        dv = DiffViewWidget()
        assert dv.side_by_side is False


def test_metadata_is_excluded_from_blame_and_highlights():
    view = DiffViewWidget()
    diff = "diff --git a/f b/f\nindex 0..1\n--- a/f\n+++ b/f\n@@ -18 +19 @@\n-old\n+new"
    view._parse_diff(diff)
    view._parse_diff_line_numbers(diff)
    assert (view._diff_line_to_file_line, view._full_file_add_lines) == ({6: 18}, {19})


async def test_return_from_message_renders_identical_diff(fixture_app):
    async with fixture_app.run_test():
        view = fixture_app.query_one(DiffViewWidget)
        view.set_diff(SAMPLE_DIFF)
        view.set_message("Same commit")
        view.set_diff(SAMPLE_DIFF)
        assert "print('new')" in "".join(line.plain for line in view._lines)


async def test_side_by_side_survives_full_file_toggle(fixture_app):
    async with fixture_app.run_test():
        view = fixture_app.query_one(DiffViewWidget)
        view.set_diff(SAMPLE_DIFF)
        view.set_full_file("content", SAMPLE_DIFF)
        view.action_toggle_side_by_side()
        view.action_toggle_full_file()
        view.action_toggle_full_file()
        assert "SIDE-BY-SIDE" in view._lines[0].plain
