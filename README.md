# CSV

Self-contained CSV package. No dependency on the Advanced CSV package.

- `CSV.sublime-syntax` — comma-only grammar, scope `text.csv`. Generic leaf
  scopes so the active color scheme styles them through existing rules: the
  first (header) row is `markup.heading.csv`, data cells are
  `string.unquoted.csv` / `string.quoted.double.csv`, numbers
  `constant.numeric.csv`, the comma a punctuation separator. Data rows
  alternate parity (`body` <-> `body-alt`); even rows add `meta.row.alt.csv`
  for a zebra foreground (dimmed via descendant rules in the scheme override).
- `csv_toggle_padding.py` — the commands:
  - `csv_toggle_padding` — toggles a buffer between compact source and a
    justified, ` , `-aligned readable form. Parses with the stdlib `csv`
    module; settings come from `CSV.sublime-settings`.
  - `csv_copy_cell` — copies the cell under each caret (trimmed, quotes
    unwrapped) instead of the whole line. Quote-aware, so commas inside
    quoted fields don't split the cell.
  - `csv_sort_by_column` — sorts data rows by the column under the caret;
    the header row stays pinned. Numbers sort numerically and before
    strings, empty cells last. Repeat on the same column to flip
    asc/desc (direction remembered per view). Works on compact and
    padded buffers alike (lines move verbatim).
  - `csv_select_column` — one selection per cell of the caret's column
    (multiple carets: multiple columns). Empty cells get a bare caret
    aligned with the padded content start.
  - `csv_select_column_by_value` — like select column but only cells
    matching the caret cell's value (case-sensitive, quote-insensitive);
    on an empty cell it targets only the column's empty cells.
- `CSV.sublime-settings` — delimiter / `delimiter_mapping` / `auto_quote`.
- `Daetherius.sublime-color-scheme` — package-local override merged into the
  active Daetherius scheme; carries the header-row color (`markup.heading.csv`).
  Data cells need no rule (their `string.*` scopes hit the theme's base string
  color). Coupled to the Daetherius scheme by filename; rename both together.
- `syntax_test_csv.csv` — run via Tools → Build (Syntax Tests).
- `tests/` — specs for the pure command logic (sublime stubbed); run
  `python3 -m unittest discover tests`.

The keybindings live in the User keymap, all gated to `text.csv` and
consolidated under the `ctrl+comma` chord prefix:

| Chord             | Command                      |
|-------------------|------------------------------|
| `ctrl+comma, tab` | `csv_toggle_padding`         |
| `ctrl+comma, s`   | `csv_sort_by_column`         |
| `ctrl+comma, c`   | `csv_select_column`          |
| `ctrl+comma, v`   | `csv_select_column_by_value` |

`super+c` is overridden to `csv_copy_cell`, gated to `text.csv` AND an empty
selection — so with text selected, or in any other file, the native `copy`
runs unchanged.

To make `.csv` open with this syntax: View → Syntax → "Open all with current
extension as…" → CSV.
