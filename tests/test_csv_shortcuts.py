"""Specs for the shortcuts popup (``csv_show_shortcuts``): every key binding
in the loaded keymaps whose command is in the package palette, labelled
with its caption, keys drawn as macOS symbols.

Pure-helper contract in csv_toggle_padding.py:

  _shortcut_rows(keymaps, palette) -> [(keys, caption), ...]
  _key_label(keys)                 -> str

Not covered, deliberately: resource loading (find_resources, decode_value),
the popup markup and its styling, which only has to look right and is
checked live.
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

PALETTE = [
    {"caption": "CSV: Move column left", "command": "csv_move_column", "args": {"forward": False}},
    {"caption": "CSV: Move column right", "command": "csv_move_column", "args": {"forward": True}},
    {"caption": "CSV: Show shortcuts", "command": "csv_show_shortcuts"},
]


class ShortcutRowsTests(unittest.TestCase):
    def test_csv_bindings_take_the_caption_matching_their_args_in_palette_order(self):
        keymaps = [
            [
                {"keys": ["ctrl+h"], "command": "csv_show_shortcuts"},
                {"keys": ["<character>"], "command": "csv_overtype"},
                {"keys": ["super+d"], "command": "duplicate_line"},
            ],
            [
                {"keys": ["ctrl+n"], "command": "csv_move_column", "args": {"forward": True}},
                {"keys": ["ctrl+p"], "command": "csv_move_column", "args": {"forward": False}},
            ],
        ]
        self.assertEqual(
            plugin._shortcut_rows(keymaps, PALETTE),
            [
                (["ctrl+p"], "Move column left"),
                (["ctrl+n"], "Move column right"),
                (["ctrl+h"], "Show shortcuts"),
            ],
        )

    def test_commands_outside_the_palette_are_left_out_and_repeats_collapse(self):
        keymaps = [
            [
                {"keys": ["ctrl+comma", "d"], "command": "csv_delete_col"},
                {"keys": ["ctrl+h"], "command": "csv_show_shortcuts"},
                {"keys": ["ctrl+h"], "command": "csv_show_shortcuts"},
            ]
        ]
        self.assertEqual(
            plugin._shortcut_rows(keymaps, PALETTE), [(["ctrl+h"], "Show shortcuts")]
        )


class KeyLabelTests(unittest.TestCase):
    def test_mac_symbols_in_menu_modifier_order(self):
        self.assertEqual(plugin._key_label(["shift+ctrl+backspace"]), "⌃⇧⌫")
        self.assertEqual(plugin._key_label(["super+c"]), "⌘C")
        self.assertEqual(plugin._key_label(["ctrl+k", "alt+tab"]), "⌃K ⌥⇥")


if __name__ == "__main__":
    unittest.main()
