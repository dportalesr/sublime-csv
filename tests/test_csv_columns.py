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
  * ``csv_move_column`` — moves the column(s) under the caret(s) one step
    left or right across every row, carets riding along. Adjacent columns
    move as a block; nothing moves past the edge.
  * ``csv_delete_column`` / ``csv_insert_column`` — delete the column(s)
    under the caret(s), or insert as many empty ones before them, in every
    row. Carets land on the column sliding in, or the first new one. The
    last remaining column can't be deleted.
  * ``csv_clear_cell`` — empties every cell a selection touches (a
    multi-row selection clears the rectangle between its corners), one
    caret per selection at the start of its first cell. Padded rows keep
    their delimiters in place.
  * ``CsvBlankCellSnapListener`` — an up/down move landing in a
    whitespace-only cell puts the caret where that cell's content starts.
  * ``csv_move_to_cell`` — tab / shift+tab: each caret selects the content
    of the next or previous cell (``tab_selects_cell``, default on) or lands
    at its start, wrapping across rows (blank lines skipped); at the
    buffer's first or last cell it stays.

Pure-helper contract in csv_toggle_padding.py:

  _row_spans(line, delimiter)                  -> [(begin, end), ...]
  _column_at(line, col, delimiter)             -> int
  _sort_key(value)                             -> orderable tuple
  _toggle_direction(state, column)             -> bool (ascending)
  _sorted_lines(lines, column, delim, asc)     -> [line, ...]
  _sort_permutation(lines, column, delim, asc) -> [new_row, ...] (old -> new)
  _column_targets(lines, column, delim)        -> [(row, begin, end), ...]
  _value_targets(lines, column, value, delim)  -> [(row, begin, end), ...]
  _column_order(columns, count, forward)       -> [old_column, ...] | None
  _moved_lines(lines, order, delim)            -> [line, ...]
  _moved_col(line, moved, col, order, delim)   -> int
  _column_edit(columns, count, insert)         -> (order, {column: position})
  _landing_col(line, position, delim)          -> int
  _clear_plan(lines, regions, delim)           -> ({row: line}, [(row, col), ...])
  _blank_cell_snap(line, col, delim)           -> int | None
  _cell_step(lines, row, col, delim, forward)  -> (row, begin, end) | None

Targets are per-line character offsets; begin == end means a bare caret.

Not covered, deliberately: Sublime wiring (run(), is_enabled, status
messages, selection restore) — thin adapters that fail loudly at runtime
and would need heavy view fakes; interior blank lines and multi-caret
column dedup (trivial loop, low blast radius); delimiter resolution
(existing behavior, unchanged).
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.modules.setdefault("sublime", types.ModuleType("sublime"))
_sublime_plugin = types.ModuleType("sublime_plugin")
_sublime_plugin.TextCommand = type("TextCommand", (), {})
_sublime_plugin.EventListener = type("EventListener", (), {})
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


class SortPermutationTests(unittest.TestCase):
    def test_maps_old_row_to_new_row_with_header_pinned(self):
        self.assertEqual(
            plugin._sort_permutation(SortedLinesTests.LINES, 1, ",", True),
            [0, 3, 1, 2, 4],
        )

    def test_descending_keeps_equal_keys_in_original_order(self):
        lines = ["h", "b,2", "a,1", "b,2"]
        self.assertEqual(
            plugin._sort_permutation(lines, 1, ",", False), [0, 1, 3, 2]
        )


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


class ColumnOrderTests(unittest.TestCase):
    def test_column_swaps_with_its_neighbour(self):
        self.assertEqual(plugin._column_order({1}, 3, True), [0, 2, 1])
        self.assertEqual(plugin._column_order({1}, 3, False), [1, 0, 2])

    def test_adjacent_columns_move_as_a_block(self):
        self.assertEqual(plugin._column_order({1, 2}, 4, True), [0, 3, 1, 2])
        self.assertEqual(plugin._column_order({1, 2}, 4, False), [1, 2, 0, 3])

    def test_nothing_moves_past_the_edge(self):
        self.assertIsNone(plugin._column_order({0}, 3, False))
        self.assertIsNone(plugin._column_order({1, 2}, 3, True))


class MovedLinesTests(unittest.TestCase):
    def test_compact_cells_move_verbatim_and_short_rows_gain_empty_cells(self):
        lines = ["name,city,zip", '"Lee, Ana",Lima,1', "Bo", ""]
        self.assertEqual(
            plugin._moved_lines(lines, [1, 0, 2], ","),
            ["city,name,zip", 'Lima,"Lee, Ana",1', ",Bo", ""],
        )

    def test_padded_rows_are_realigned(self):
        lines = ["id , name", "1  , Ana", "22 , Bo"]
        self.assertEqual(
            plugin._moved_lines(lines, [1, 0], ","),
            ["name , id", "Ana  , 1", "Bo   , 22"],
        )


class ColumnEditTests(unittest.TestCase):
    def test_delete_keeps_the_others_and_lands_on_the_column_sliding_in(self):
        self.assertEqual(plugin._column_edit({1}, 3, False), ([0, 2], {1: 1}))
        self.assertEqual(plugin._column_edit({2}, 3, False), ([0, 1], {2: 2}))

    def test_insert_puts_one_empty_column_per_selected_one_before_the_run(self):
        self.assertEqual(
            plugin._column_edit({1, 2}, 4, True), ([0, None, None, 1, 2, 3], {1: 1, 2: 1})
        )


class EditedLinesTests(unittest.TestCase):
    def test_compact_rows_gain_empty_cells_or_lose_deleted_ones(self):
        lines = ["a,b,c", "x", ""]
        self.assertEqual(
            plugin._moved_lines(lines, [0, None, 1, 2], ","), ["a,,b,c", "x", ""]
        )
        self.assertEqual(plugin._moved_lines(["a,b", "x"], [1], ","), ["b", ""])

    def test_padded_rows_realign_after_a_delete(self):
        lines = ["id , name , age", "1  , Ana  , 30"]
        self.assertEqual(
            plugin._moved_lines(lines, [0, 2], ","), ["id , age", "1  , 30"]
        )


class LandingColTests(unittest.TestCase):
    def test_content_start_of_the_cell_clamped_to_the_last_one(self):
        self.assertEqual(plugin._landing_col("a , bb", 1, ","), 4)
        self.assertEqual(plugin._landing_col("a , bb", 5, ","), 4)


class MovedColTests(unittest.TestCase):
    def test_caret_keeps_its_offset_in_the_cell_it_was_in(self):
        line, moved, order = "ab,cde,f", "ab,f,cde", [0, 2, 1]
        self.assertEqual(plugin._moved_col(line, moved, 5, order, ","), 7)
        self.assertEqual(plugin._moved_col(line, moved, 8, order, ","), 4)

    def test_padded_empty_cell_caret_lands_on_the_content_anchor(self):
        line, moved, order = "x ,    , z", "   , x , z", [1, 0, 2]
        self.assertEqual(plugin._moved_col(line, moved, 5, order, ","), 0)
        self.assertEqual(plugin._moved_col(line, moved, 0, order, ","), 5)


class ClearPlanTests(unittest.TestCase):
    def test_compact_cells_empty_and_carets_land_at_the_cell_start(self):
        lines = ["h,x,y", "a,bcd,e", '"Lee, Ana",1']
        self.assertEqual(
            plugin._clear_plan(lines, [(1, 3, 1, 3), (2, 4, 2, 4)], ","),
            ({1: "a,,e", 2: ",1"}, [(1, 2), (2, 0)]),
        )

    def test_padded_row_keeps_its_delimiters_in_place(self):
        lines = ["h , xxx , y", "a , bcd , e"]
        self.assertEqual(
            plugin._clear_plan(lines, [(1, 5, 1, 5), (1, 10, 1, 10)], ","),
            ({1: "a ,     , "}, [(1, 4), (1, 10)]),
        )

    def test_selection_clears_the_rectangle_it_spans(self):
        lines = ["h,x,y", "a,b,c", "d,e,f"]
        self.assertEqual(
            plugin._clear_plan(lines, [(1, 0, 2, 3)], ","),
            ({1: ",,c", 2: ",,f"}, [(1, 0)]),
        )


class BlankCellSnapTests(unittest.TestCase):
    def test_blank_padded_cell_snaps_to_content_start(self):
        self.assertEqual(plugin._blank_cell_snap("x ,   , z", 5, ","), 4)

    def test_padding_after_content_is_not_a_blank_cell(self):
        self.assertIsNone(plugin._blank_cell_snap("x , ab  , z", 7, ","))

    def test_overflowed_row_uses_the_cell_under_the_caret(self):
        self.assertIsNone(plugin._blank_cell_snap("abcdef ,    , c", 5, ","))


class CellStepTests(unittest.TestCase):
    def test_steps_to_the_neighbour_cell_content_quotes_included(self):
        lines = ['a , "x, y" , c']
        self.assertEqual(plugin._cell_step(lines, 0, 0, ",", True), (0, 4, 10))
        self.assertEqual(plugin._cell_step(lines, 0, 5, ",", False), (0, 0, 1))

    def test_wraps_across_rows_skipping_blank_lines(self):
        lines = ["a,b", "", "c,d"]
        self.assertEqual(plugin._cell_step(lines, 0, 3, ",", True), (2, 0, 1))
        self.assertEqual(plugin._cell_step(lines, 2, 0, ",", False), (0, 2, 3))

    def test_stays_at_the_buffer_edges(self):
        lines = ["a,b", "c,d", ""]
        self.assertIsNone(plugin._cell_step(lines, 1, 3, ",", True))
        self.assertIsNone(plugin._cell_step(lines, 0, 0, ",", False))


class TogglePaddingRoundTripTests(unittest.TestCase):
    def test_padded_quoted_cells_collapse_back_to_source(self):
        src = 'a,b,c\nz,"x, y","say ""hi"""'
        expanded = plugin._format_expanded(plugin._parse(src, ","), ",", True)
        rows = plugin._parse(expanded, ",")
        self.assertEqual(plugin._format_expanded(rows, ",", True), expanded)
        self.assertEqual(plugin._format_compact(rows, ",", True), src)


if __name__ == "__main__":
    unittest.main()
