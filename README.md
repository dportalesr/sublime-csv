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
  - `csv_move_column` — moves the caret's column one step right
    (`forward: true`) or left across every row; carets ride along, so
    repeated presses keep carrying it. A selection moves every column it
    spans, adjacent columns move as a block, nothing moves past the edge.
    Compact cells move verbatim; a padded buffer is realigned.
  - `csv_insert_column` / `csv_delete_column` - insert an empty column
    before the caret's column (one per selected column, before the run) or
    delete the spanned columns, in every row. Carets land in the new column,
    or on the one sliding into the gap. The last column can't be deleted.
    Compact cells stay verbatim; a padded buffer is realigned.
  - `csv_clear_cell` — empties the cell under each caret (quotes included)
    and leaves the caret where its content starts. A selection clears every
    cell it touches; across rows, the rectangle between its corners. Padded
    rows keep their delimiters in place, so typing overtypes.
  - `csv_overtype` - typing into a padded cell eats the spaces before its
    closing delimiter, so the delimiter stays in its column until the
    padding runs out; backspace and delete put spaces back. A selection
    inside one cell (a quoted value with a delimiter counts as one cell)
    is replaced or deleted the same way, so tab-select-then-type and
    select-column-then-backspace keep the columns aligned. At a cell's
    edge, backspace and delete stop instead of taking the gutter space, a
    delimiter or a line break; restructure with the column commands or in
    compact form. Auto-paired brackets and quotes absorb two. Inert in
    compact form.
  - `csv_move_to_cell` - spreadsheet-style tab: each caret goes to the
    next (`forward: true`) or previous cell, wrapping across rows and
    skipping blank lines; at the buffer's first or last cell it stays. With
    `tab_selects_cell` (default on) it selects the cell's content, quotes
    included, so typing replaces it; off, it lands at the content start. A
    tab-delimited view inserts a tab instead.
  - `csv_show_shortcuts` - popup at the caret listing every key binding
    whose command is in this package's palette, read from the loaded
    keymaps on each call so it always matches the real keys; labels are
    the palette captions, order is the palette's.
  - Blank-cell snap (listener, no key) - an up/down move landing in a
    whitespace-only cell puts the caret where that cell's content starts,
    like Home. Selections, page moves and left/right stay native.
- `CSV.sublime-settings` — delimiter / `delimiter_mapping` / `auto_quote` /
  `tab_selects_cell`.
- `Daetherius.sublime-color-scheme` — package-local override merged into the
  active Daetherius scheme; carries the header-row color (`markup.heading.csv`).
  Data cells need no rule (their `string.*` scopes hit the theme's base string
  color). Coupled to the Daetherius scheme by filename; rename both together.
- `syntax_test_csv.csv` — run via Tools → Build (Syntax Tests).
- `tests/` — specs for the pure command logic (sublime stubbed); run
  `python3 -m unittest discover tests`.

The keybindings live in the User keymap, all gated to `text.csv`. Plain keys
go without `ctrl` where the scope makes them safe; letters keep it. `tab`
yields to snippet fields and the completion popup. `ctrl+backspace` has to
sit after any global binding of the same key, since the last match wins.

| Keys             | Command                               |
|------------------|---------------------------------------|
| `alt+tab`        | `csv_toggle_padding`                  |
| `tab`            | `csv_move_to_cell` (`forward: true`)  |
| `shift+tab`      | `csv_move_to_cell` (`forward: false`) |
| `ctrl+backspace` | `csv_clear_cell`                      |
| `ctrl+s`         | `csv_sort_by_column`                  |
| `ctrl+c`         | `csv_select_column`                   |
| `ctrl+v`         | `csv_select_column_by_value`          |
| `ctrl+i`         | `csv_insert_column`                   |
| `ctrl+d`         | `csv_delete_column`                   |
| `ctrl+p`         | `csv_move_column` (`forward: false`)  |
| `ctrl+n`         | `csv_move_column` (`forward: true`)   |
| `ctrl+h`         | `csv_show_shortcuts`                  |

`super+c` is overridden to `csv_copy_cell`, gated to `text.csv` AND an empty
selection — so with text selected, or in any other file, the native `copy`
runs unchanged.

`Default.sublime-keymap` is mechanism, not shortcuts: it binds
`<character>` to `csv_overtype` (gated by its own `csv_overtype` context) and
carries copies of Default's auto-pair bindings, which `<character>` would
otherwise shadow. Refresh the copies if Sublime changes its defaults.

To make `.csv` open with this syntax: View → Syntax → "Open all with current
extension as…" → CSV.
