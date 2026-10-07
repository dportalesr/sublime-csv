# CSV for Sublime Text

A Sublime Text 4 package for editing CSV files. It adds a CSV syntax with a
highlighted header and optional zebra rows, a toggle between the compact
file and a readable form with aligned columns, and spreadsheet-style editing
in that aligned form: tab between cells, type over a cell without pushing
the next column, and move, insert or delete whole columns.

## Installation

Clone the repository into your Packages folder (Preferences → Browse
Packages…) as `CSV`:

```sh
git clone https://github.com/dportalesr/sublime-csv.git CSV
```

Files ending in `.csv` open with the CSV syntax. For other extensions, open
one and pick View → Syntax → Open all with current extension as… → CSV.

The package ships no shortcuts of its own; see [Keybindings](#keybindings)
for a suggested set.

## Aligned columns

**CSV: Toggle column padding** switches the file between its compact form

```
id,name,city
1,Ana López,Lima
22,Bo,"Oslo, Norway"
```

and an aligned form, where every column is padded to its widest cell and
the delimiters line up as column separators:

```
id , name      , city
1  , Ana López , Lima
22 , Bo        , "Oslo, Norway"
```

The command decides what to do from the file itself. A compact file gets
aligned, an aligned file that you have edited out of line gets realigned,
and a file that is already aligned collapses back to compact. A typical
session is: align, edit, collapse, save. Collapse before saving if other
tools read the file, since most CSV readers keep the padding spaces as part
of the values.

## Spreadsheet-style editing

These behaviours apply while the file is in its aligned form; in the compact
form, editing works as in any text file.

- **Overtype.** Typing in a cell uses up the padding before the next
  delimiter, so the columns to the right stay in place until the padding
  runs out. Backspace and delete give the spaces back. Typing over,
  deleting or cutting a selection inside one cell works the same way.
- **Paste.** Pasting counts as typing: copy a cell, move to another row and
  paste, and the columns stay aligned. With several carets and a clipboard
  holding one line per caret, each caret gets its own line, as elsewhere in
  Sublime.
- **Cut.** A cut over several carets puts one line per caret on the
  clipboard, an empty one for a caret with nothing selected. Cut a selected
  column that has blank cells, paste it over another column, and every value
  lands on its own row.
- **Cell edges.** Backspace and delete stop at the edge of a cell instead of
  removing the delimiter or joining two rows. To restructure, use the column
  commands below or switch to the compact form.
- **Tab between cells.** Next and previous cell move each caret across the
  row and wrap to the next or previous row. By default the cell's content is
  selected, so typing replaces it; see the `tab_selects_cell` setting.
- **Blank cells.** Moving up or down into an empty cell puts the caret where
  its content would start, not somewhere in the middle of the padding.

## Commands

All commands are in the command palette under **CSV:** and work with
multiple carets.

| Command                  | What it does                                                           |
|--------------------------|------------------------------------------------------------------------|
| Toggle column padding    | Aligns, realigns or collapses the columns, as described above.         |
| Next cell, Previous cell | Moves to the neighbouring cell, wrapping across rows.                  |
| Copy cell                | Copies the value under each caret: trimmed, quotes removed.            |
| Cut cell                 | Copies the value under each caret like Copy cell, then empties it.     |
| Clear cell               | Empties the cell under each caret, or every cell a selection touches.  |
| Sort by column           | Sorts rows by the caret's column, header kept on top; again reverses.  |
| Select column            | Selects every cell in the caret's column.                              |
| Select column by value   | Selects the cells in the caret's column that hold the same value.      |
| Insert column            | Inserts an empty column before the caret's column.                     |
| Delete column            | Deletes the caret's column; a selection deletes every column it spans. |
| Move column left, right  | Moves the caret's column one place; the caret moves with it.           |
| Show shortcuts           | Lists your CSV key bindings in a popup, read from your keymaps.        |

Sort puts numbers before text and compares them numerically; empty cells go
last.

## Keybindings

The package does not bind any shortcuts, so it won't clash with yours. The
set below is the one the package was built with, for macOS. Every binding is
limited to CSV files, so the `ctrl` keys don't affect other files. On
Windows and Linux, `ctrl+s`, `ctrl+c` and `ctrl+v` are save, copy and paste,
so choose other keys there.

Add the entries you want to your keymap (Preferences → Key Bindings):

```json
[
  { "keys": ["alt+tab"], "command": "csv_toggle_padding", "context": [{ "key": "selector", "operand": "text.csv" }] },
  { "keys": ["tab"], "command": "csv_move_to_cell", "args": { "forward": true }, "context": [
      { "key": "selector", "operand": "text.csv" },
      { "key": "has_next_field", "operand": false },
      { "key": "auto_complete_visible", "operand": false }
  ] },
  { "keys": ["shift+tab"], "command": "csv_move_to_cell", "args": { "forward": false }, "context": [
      { "key": "selector", "operand": "text.csv" },
      { "key": "has_prev_field", "operand": false },
      { "key": "auto_complete_visible", "operand": false }
  ] },
  { "keys": ["super+c"], "command": "csv_copy_cell", "context": [
      { "key": "selector", "operand": "text.csv" },
      { "key": "selection_empty", "operand": true, "match_all": true }
  ] },
  { "keys": ["super+x"], "command": "csv_cut_cell", "context": [
      { "key": "selector", "operand": "text.csv" },
      { "key": "selection_empty", "operand": true, "match_all": true }
  ] },
  { "keys": ["ctrl+backspace"], "command": "csv_clear_cell", "context": [{ "key": "selector", "operand": "text.csv" }] },
  { "keys": ["ctrl+s"], "command": "csv_sort_by_column", "context": [{ "key": "selector", "operand": "text.csv" }] },
  { "keys": ["ctrl+c"], "command": "csv_select_column", "context": [{ "key": "selector", "operand": "text.csv" }] },
  { "keys": ["ctrl+v"], "command": "csv_select_column_by_value", "context": [{ "key": "selector", "operand": "text.csv" }] },
  { "keys": ["ctrl+i"], "command": "csv_insert_column", "context": [{ "key": "selector", "operand": "text.csv" }] },
  { "keys": ["ctrl+d"], "command": "csv_delete_column", "context": [{ "key": "selector", "operand": "text.csv" }] },
  { "keys": ["ctrl+p"], "command": "csv_move_column", "args": { "forward": false }, "context": [{ "key": "selector", "operand": "text.csv" }] },
  { "keys": ["ctrl+n"], "command": "csv_move_column", "args": { "forward": true }, "context": [{ "key": "selector", "operand": "text.csv" }] },
  { "keys": ["ctrl+h"], "command": "csv_show_shortcuts", "context": [{ "key": "selector", "operand": "text.csv" }] }
]
```

A few notes on these:

- `tab` still expands snippet fields and accepts completions; the extra
  conditions hand it back in those cases.
- `super+c` and `super+x` copy or cut just the cell only when nothing is
  selected; with a selection they work as usual. Without the `super+x`
  entry, cutting with nothing selected takes the whole row, as elsewhere in
  Sublime; with it, select the row first to cut it.
- When two bindings for the same key both apply, Sublime uses the later one.
  If your keymap already binds `ctrl+backspace` for all files, put the CSV
  entry after it.

## Settings

Override any of these in `Packages/User/CSV.sublime-settings`, or for a
single file through its view settings.

| Setting             | Default                               | Meaning                                                                    |
|---------------------|---------------------------------------|----------------------------------------------------------------------------|
| `delimiter`         | `","`                                 | Delimiter when nothing more specific applies.                              |
| `delimiter_mapping` | `.csv` comma, `.tsv` tab, `.psv` pipe | Delimiter per file name pattern.                                           |
| `auto_quote`        | `true`                                | Quote values that contain the delimiter or a quote when aligning.          |
| `tab_selects_cell`  | `true`                                | Next and previous cell select the content; `false` places a caret instead. |

## Colors

The syntax uses generic scopes, so most color schemes style CSV files
without changes:

| Part                  | Scope                                |
|-----------------------|--------------------------------------|
| Header row            | `markup.heading.csv`                 |
| Plain cells           | `string.unquoted.csv`                |
| Quoted cells          | `string.quoted.double.csv`           |
| Numbers               | `constant.numeric.csv`               |
| Delimiters            | `punctuation.separator.sequence.csv` |
| Every second data row | `meta.row.alt.csv`                   |

The package sets no colors itself. `meta.row.alt.csv` stays uncolored until
your scheme gives it one, so zebra rows are opt-in. To add them, or to
restyle the header, add rules through UI → Customize Color Scheme, for
example:

```json
{
  "rules": [
    { "scope": "markup.heading.csv", "foreground": "#00cccc" },
    { "scope": "meta.row.alt.csv", "background": "#00000055" }
  ]
}
```

## Limitations

- Only commas are highlighted. The commands honor other delimiters, but a
  tab- or pipe-separated file shows as a single column.
- Quoted values that span several lines are not supported.
- In the aligned form, typing a quote or bracket over a selection (which
  wraps it), or pasting text that contains a delimiter, a tab or a line
  break can shift the rest of the row. Toggle column padding realigns it.
- Copy cell and Cut cell remove a value's quotes, so a value that contains
  the delimiter pastes back as two cells. To keep it whole, select the
  quoted value and copy or cut that.
- To provide overtype, the package takes over typing in CSV files, so it
  carries copies of Sublime's auto-pairing bindings for quotes and
  brackets. A future Sublime release that changes those bindings may need
  the copies updated.

## Development

The command logic is covered by unit tests that run without Sublime Text:

```sh
python3 -m unittest discover tests
```

The syntax test runs inside Sublime: open `syntax_test_csv.csv` and use
Tools → Build.

## License

MIT, see [LICENSE](LICENSE).
