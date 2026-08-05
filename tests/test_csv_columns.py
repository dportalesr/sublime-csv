"""Specs for the CSV column commands: sort by column, select column,
select column by value.

Commands (thin wrappers over the pure helpers tested here):

  * ``csv_sort_by_column`` — sorts data rows by the column under the first
    caret. Row 0 is the header and stays pinned. Re-invoking on the same
    column flips ASC <-> DESC; a different column resets to ASC. Direction
    state lives in the view settings (``csv_sort``).
  * ``csv_select_column`` — one selection per cell of the caret's column,
    covering the trimmed cell token (quotes included). Empty cells get a
    caret aligned where content starts in the padded form. Multiple carets
    select multiple columns.
  * ``csv_select_column_by_value`` — like select column, but only cells
    whose logical value equals the caret cell's value (case-sensitive;
    quoted and bare forms of the same value match). An empty caret cell
    targets only the column's empty cells.

Pure-helper contract in csv_toggle_padding.py:

  _row_spans(line, delimiter)                  -> [(begin, end), ...]
  _column_at(line, col, delimiter)             -> int
  _sort_key(value)                             -> orderable tuple
  _toggle_direction(state, column)             -> bool (ascending)
  _sorted_lines(lines, column, delim, asc)     -> [line, ...]
  _column_targets(lines, column, delim)        -> [(row, begin, end), ...]
  _value_targets(lines, column, value, delim)  -> [(row, begin, end), ...]

Targets are per-line character offsets; begin == end means a bare caret.

Not covered, deliberately: Sublime wiring (run(), is_enabled, status
messages, selection restore) — thin adapters that fail loudly at runtime
and would need heavy view fakes; equal-key sort stability (stdlib
guarantee); interior blank lines and multi-caret column dedup (trivial
loop, low blast radius); delimiter resolution (existing behavior,
unchanged).
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.modules.setdefault("sublime", types.ModuleType("sublime"))
_sublime_plugin = types.ModuleType("sublime_plugin")
_sublime_plugin.TextCommand = type("TextCommand", (), {})
sys.modules.setdefault("sublime_plugin", _sublime_plugin)

import csv_toggle_padding as plugin


class RowSpansTests(unittest.TestCase):
    def test_splits_line_into_cell_spans(self):
        self.assertEqual(plugin._row_spans("a,b,c", ","), [(0, 1), (2, 3), (4, 5)])

    def test_quoted_delimiter_does_not_split(self):
        self.assertEqual(plugin._row_spans('"a,b",c', ","), [(0, 5), (6, 7)])


class ColumnAtTests(unittest.TestCase):
    def test_caret_maps_to_containing_column(self):
        self.assertEqual(plugin._column_at("a,b,c", 0, ","), 0)
        self.assertEqual(plugin._column_at("a,b,c", 2, ","), 1)
        self.assertEqual(plugin._column_at("a,b,c", 5, ","), 2)

    def test_caret_on_delimiter_belongs_to_field_it_closes(self):
        self.assertEqual(plugin._column_at("a,b,c", 1, ","), 0)

    def test_padded_line(self):
        self.assertEqual(plugin._column_at("aa , b", 5, ","), 1)


class SortKeyTests(unittest.TestCase):
    def test_numbers_before_strings_casefolded_empties_last(self):
        values = ["10", "2", "apple", "Banana", ""]
        ordered = sorted(values, key=plugin._sort_key)
        self.assertEqual(ordered, ["2", "10", "apple", "Banana", ""])


class ToggleDirectionTests(unittest.TestCase):
    def test_direction_state_transitions(self):
        self.assertTrue(plugin._toggle_direction(None, 1))
        self.assertFalse(plugin._toggle_direction({"column": 1, "ascending": True}, 1))
        self.assertTrue(plugin._toggle_direction({"column": 1, "ascending": False}, 1))
        self.assertTrue(plugin._toggle_direction({"column": 1, "ascending": True}, 2))


class SortedLinesTests(unittest.TestCase):
    LINES = [
        "name,age,city",
        "Bo,12,Oslo",
        "Ana,3,Lima",
        "Cy,7,",
        "",
    ]

    def test_numeric_asc_pins_header_and_trailing_blank(self):
        self.assertEqual(
            plugin._sorted_lines(self.LINES, 1, ",", True),
            ["name,age,city", "Ana,3,Lima", "Cy,7,", "Bo,12,Oslo", ""],
        )

    def test_desc_reverses(self):
        self.assertEqual(
            plugin._sorted_lines(self.LINES, 1, ",", False),
            ["name,age,city", "Bo,12,Oslo", "Cy,7,", "Ana,3,Lima", ""],
        )

    def test_string_column_sorts_casefolded_empties_last(self):
        self.assertEqual(
            plugin._sorted_lines(self.LINES, 2, ",", True),
            ["name,age,city", "Ana,3,Lima", "Bo,12,Oslo", "Cy,7,", ""],
        )

    def test_quoted_cells_sort_by_logical_value(self):
        lines = ["h", 'a,"10"', "b,2"]
        self.assertEqual(
            plugin._sorted_lines(lines, 1, ",", True), ["h", "b,2", 'a,"10"']
        )

    def test_padded_lines_reorder_verbatim(self):
        lines = ["name , age", "Bo   , 12", "Ana  , 3"]
        self.assertEqual(
            plugin._sorted_lines(lines, 1, ",", True),
            ["name , age", "Ana  , 3", "Bo   , 12"],
        )

    def test_row_missing_the_column_sorts_as_empty(self):
        lines = ["h,x", "a", "b,1"]
        self.assertEqual(plugin._sorted_lines(lines, 1, ",", True), ["h,x", "b,1", "a"])


class ColumnTargetsTests(unittest.TestCase):
    def test_selects_trimmed_cells_including_header(self):
        lines = ["name,city", "Ana,Lima", "Bo,"]
        self.assertEqual(
            plugin._column_targets(lines, 1, ","),
            [(0, 5, 9), (1, 4, 8), (2, 3, 3)],
        )

    def test_quoted_cell_selection_includes_quotes(self):
        lines = ["h,q", 'x,"a,b"']
        self.assertEqual(
            plugin._column_targets(lines, 1, ","), [(0, 2, 3), (1, 2, 7)]
        )

    def test_padded_empty_cell_caret_aligns_with_content_start(self):
        lines = ["a , b , c", "x ,   , z"]
        self.assertEqual(
            plugin._column_targets(lines, 1, ","), [(0, 4, 5), (1, 4, 4)]
        )

    def test_empty_first_column_caret_at_line_start(self):
        self.assertEqual(plugin._column_targets([",b"], 0, ","), [(0, 0, 0)])

    def test_skips_short_rows_and_blank_lines(self):
        lines = ["a,b", "only", ""]
        self.assertEqual(plugin._column_targets(lines, 1, ","), [(0, 2, 3)])


class ValueTargetsTests(unittest.TestCase):
    def test_matches_logical_value_quoted_or_bare(self):
        lines = ["city,check", "NY,1", '"NY",2', "ny,3", "LA,"]
        self.assertEqual(
            plugin._value_targets(lines, 0, "NY", ","),
            [(1, 0, 2), (2, 0, 4)],
        )

    def test_match_is_case_sensitive(self):
        lines = ["h", "ny,1"]
        self.assertEqual(plugin._value_targets(lines, 0, "NY", ","), [])

    def test_empty_value_targets_only_empty_cells(self):
        lines = ["h,x", "a,", "b,2", "c,"]
        self.assertEqual(
            plugin._value_targets(lines, 1, "", ","),
            [(1, 2, 2), (3, 2, 2)],
        )


if __name__ == "__main__":
    unittest.main()
