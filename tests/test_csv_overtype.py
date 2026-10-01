"""Specs for overtype padding: typing into a padded cell consumes the spaces
before its closing delimiter, so the delimiter keeps its column until the
padding runs out; shrinking edits put spaces back.

Pure-helper contract in csv_toggle_padding.py:

  _is_padded_row(line, delim)                       -> bool
  _pair_snippet(contents)                           -> (open, close, wraps) | None
  _overtype_edits(line, regions, text, delim, padded, tail, keep)
                                                    -> (edits, carets, absorbed) | None
  _overtype_plan(lines, regions, text, delim, delete, tail, keep)
                                                    -> ({row: edits}, selections, absorbed) | None

Not covered, deliberately: Sublime glue (key binding, context key, listener
rewrites, reverse-order replace, selection rebuild, scroll follow, undo
granularity), checked live instead; the delete-mode line-boundary guard
and tab delimiters, both one-line pass-throughs.
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


def _apply(line, edits):
    for begin, end, replacement in reversed(edits):
        line = line[:begin] + replacement + line[end:]
    return line


def _type(line, regions, text, padded=True):
    edits, carets, absorbed = plugin._overtype_edits(line, regions, text, ",", padded)
    return _apply(line, edits), carets, absorbed


class OvertypeEditsTests(unittest.TestCase):
    def test_typed_text_consumes_trailing_padding(self):
        self.assertEqual(
            _type("         , PROD-5536", [(0, 0)], "statu"),
            ("statu    , PROD-5536", [5], 5),
        )

    def test_gutter_goes_last_and_only_the_trailing_run_absorbs(self):
        self.assertEqual(
            _type("status:  , PROD", [(8, 8)], "d"), ("status: d, PROD", [9], 1)
        )
        self.assertEqual(
            _type("status: d, PROD", [(9, 9)], " "), ("status: d , PROD", [10], 0)
        )
        self.assertEqual(
            _type("status: d, PROD", [(0, 0)], "x"), ("xstatus: d, PROD", [1], 0)
        )

    def test_caret_inside_padding_absorbs_only_spaces_after_the_text(self):
        self.assertEqual(_type("statu    , x", [(7, 7)], "x"), ("statu  x , x", [8], 1))
        self.assertEqual(_type("statu    , x", [(9, 9)], "x"), ("statu    x, x", [10], 0))

    def test_carets_sharing_a_cell_share_its_padding(self):
        self.assertEqual(
            _type("ab  , x", [(0, 0), (1, 1), (2, 2)], "x"), ("xaxbx, x", [1, 3, 5], 2)
        )

    def test_delimiter_inside_quotes_does_not_close_the_cell(self):
        self.assertEqual(_type('"a  , b" , x', [(2, 2)], "x"), ('"ax  , b", x', [3], 1))

    def test_selected_quoted_value_with_a_delimiter_is_one_cell(self):
        self.assertEqual(
            _type('1 , "Bo, Jr" , 40', [(4, 12)], "x"),
            ("1 , x" + " " * 8 + ", 40", [5], 7),
        )

    def test_last_cell_keeps_its_trailing_spaces(self):
        self.assertEqual(_type("a , bc  ", [(6, 6)], "d"), ("a , bcd  ", [7], 0))

    def test_structural_regions_are_left_to_native(self):
        self.assertIsNone(plugin._overtype_edits("a , b", [(1, 4)], "x", ",", True))
        self.assertIsNone(plugin._overtype_edits('"a"  , x', [(2, 3)], "", ",", True))

    def test_shrinking_edits_restore_padding_before_the_delimiter(self):
        self.assertEqual(_type("statu    , x", [(1, 2)], ""), ("satu     , x", [1], 1))
        self.assertEqual(_type("ab, c", [(1, 2)], "", padded=False), ("a, c", [1], 0))
        self.assertEqual(_type("12,foo", [(1, 2)], ""), ("1,foo", [1], 0))

    def test_row_trimmed_after_an_empty_last_cell_still_restores(self):
        self.assertEqual(_type("x , y ,", [(4, 5)], ""), ("x ,   ,", [4], 1))


class PaddedRowTests(unittest.TestCase):
    def test_padded_row_detection_ignores_quoted_separators(self):
        self.assertTrue(plugin._is_padded_row("a , b", ","))
        self.assertFalse(plugin._is_padded_row("a,b", ","))
        self.assertFalse(plugin._is_padded_row('"x , y",z', ","))


class OvertypePlanTests(unittest.TestCase):
    def test_plan_is_all_or_nothing(self):
        lines = {0: "h , k", 1: "ab   , x", 2: "a , b"}
        self.assertEqual(
            plugin._overtype_plan(lines, [(1, 2, 1, 2)], "x", ","),
            ({1: [(0, 5, "abx  ")]}, [(1, 3, 3)], 1),
        )
        self.assertIsNone(
            plugin._overtype_plan(lines, [(1, 2, 1, 2), (2, 1, 2, 4)], "x", ",")
        )
        self.assertIsNone(
            plugin._overtype_plan({0: "h,k", 1: "a,b"}, [(1, 1, 1, 1)], "x", ",")
        )
        unbalanced = {0: "h , k", 1: 'size 5"   , "x  , y" , z'}
        self.assertIsNone(plugin._overtype_plan(unbalanced, [(1, 14, 1, 14)], "Q", ","))

    def test_padded_deletes_stop_at_cell_edges(self):
        lines = {0: "id , name", 1: "1  , Ana , x"}
        for col, side in ((5, "left"), (0, "left"), (9, "right")):
            self.assertEqual(
                plugin._overtype_plan(lines, [(1, col, 1, col)], "", ",", delete=side),
                ({}, [(1, col, col)], 0),
            )
        compact = {0: "h,k", 1: "ab,c"}
        self.assertIsNone(plugin._overtype_plan(compact, [(1, 3, 1, 3)], "", ",", delete="left"))

    def test_a_caret_stopped_at_an_edge_does_not_block_the_others(self):
        lines = {0: "id , name", 1: "1  , Ana , x", 2: "2  , Bo  , y"}
        self.assertEqual(
            plugin._overtype_plan(lines, [(1, 5, 1, 5), (2, 7, 2, 7)], "", ",", delete="left"),
            ({2: [(4, 9, " B   ")]}, [(1, 5, 5), (2, 6, 6)], 1),
        )

    def test_delete_on_a_selection_empties_it_and_restores_padding(self):
        lines = {0: "id , name", 1: "1  , Ana  , 30"}
        self.assertEqual(
            plugin._overtype_plan(lines, [(1, 5, 1, 8)], "", ",", delete="left"),
            ({1: [(4, 10, " " * 6)]}, [(1, 5, 5)], 3),
        )


class PairTests(unittest.TestCase):
    def test_pair_snippet_accepts_only_single_character_pairs(self):
        self.assertEqual(plugin._pair_snippet("($0)"), ("(", ")", False))
        self.assertEqual(plugin._pair_snippet("(${0:$SELECTION})"), ("(", ")", True))
        self.assertIsNone(plugin._pair_snippet("($1)"))
        self.assertIsNone(plugin._pair_snippet("(($0))"))

    def test_pair_snippets_absorb_two_and_keep_the_caret_inside(self):
        lines = {0: "h , k", 1: "ab   , x"}
        self.assertEqual(
            plugin._overtype_plan(lines, [(1, 2, 1, 2)], '"', ",", tail='"'),
            ({1: [(0, 5, 'ab"" ')]}, [(1, 3, 3)], 2),
        )
        self.assertIsNone(plugin._overtype_plan(lines, [(1, 2, 1, 2)], '"', ","))
        self.assertEqual(
            plugin._overtype_plan(lines, [(1, 0, 1, 2)], "(", ",", tail=")", keep=True),
            ({1: [(0, 5, "(ab) ")]}, [(1, 1, 3)], 2),
        )
        emptied = {0: "h , k", 1: 'ab"" , x'}
        self.assertEqual(
            plugin._overtype_plan(emptied, [(1, 3, 1, 3)], "", ",", delete="pair"),
            ({1: [(0, 5, "ab   ")]}, [(1, 2, 2)], 2),
        )


if __name__ == "__main__":
    unittest.main()
