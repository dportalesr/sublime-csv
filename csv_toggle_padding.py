"""
CSV: Toggle column padding.

One self-contained, dependency-free command toggles a CSV buffer between
its compact source form and a readable expanded form whose columns are
aligned with a `PADDING`-space gutter on each side of every delimiter,
turning the delimiters themselves into visual column separators:

    add padding -> edit cells -> (re-pad) -> collapse -> save

A single invocation derives what to do from the buffer's own content,
so there is no per-view flag to drift out of sync:

  * Compact source            -> expand (pad + align).
  * Expanded but misaligned    -> re-expand (realign after edits).
  * Expanded and aligned       -> collapse back to compact source.

In other words it "settles, then collapses": keep pressing while you edit
and it keeps realigning; once it is already perfectly aligned the next
press collapses it for saving.

This plugin is self-contained and has no dependency on the Advanced CSV
package: it pairs with the sibling `CSV.sublime-syntax` (scope `text.csv`)
and reads its own `CSV.sublime-settings`. Parsing uses the stdlib `csv`
module; delimiter and quoting resolve from per-view `delimiter` > the
`delimiter_mapping` glob > the `delimiter` default, degrading gracefully
to comma / auto-quote when the settings file is absent.

Cell whitespace is stripped before measuring, which is what makes the
expanded form a fixed point: realigning never grows the gutter, and the
"is this already expanded?" check stays exact.
"""

import csv
import fnmatch
import io

import sublime
import sublime_plugin

PADDING = 1
SETTINGS_FILE = "CSV.sublime-settings"
CSV_SCOPE = "text.csv"


def _is_csv_view(view):
    return view is not None and view.match_selector(0, CSV_SCOPE)


def _view_or_user_setting(view, settings, name, default):
    view_settings = view.settings()
    if view_settings.has(name):
        return view_settings.get(name)
    return settings.get(name, default)


def _choose_delimiter(view, settings):
    delimiter = None

    view_settings = view.settings()
    if view_settings.has("delimiter"):
        delimiter = view_settings.get("delimiter")

    if not delimiter:
        filename = view.file_name()
        if filename:
            mapping = settings.get("delimiter_mapping", {}) or {}
            for pattern, value in mapping.items():
                if fnmatch.fnmatch(filename, pattern):
                    delimiter = value
                    break

    if not delimiter:
        delimiter = settings.get("delimiter", ",")

    if delimiter == "\\t":
        delimiter = "\t"

    if not isinstance(delimiter, str) or len(delimiter) != 1:
        delimiter = ","

    return delimiter


def _quote(text, delimiter, auto_quote):
    if not auto_quote:
        return text
    if delimiter in text or '"' in text:
        return '"' + text.replace('"', '""') + '"'
    return text


def _parse(text, delimiter):
    return list(csv.reader(io.StringIO(text), delimiter=delimiter, quotechar='"'))


def _format_compact(rows, delimiter, auto_quote):
    lines = []
    for row in rows:
        cells = [_quote(cell.strip(), delimiter, auto_quote) for cell in row]
        lines.append(delimiter.join(cells))
    return "\n".join(lines)


def _format_expanded(rows, delimiter, auto_quote, padding=PADDING):
    num_columns = max((len(row) for row in rows), default=0)

    widths = [0] * num_columns
    for row in rows:
        for index, cell in enumerate(row):
            width = len(_quote(cell.strip(), delimiter, auto_quote))
            if width > widths[index]:
                widths[index] = width

    separator = " " * padding + delimiter + " " * padding
    lines = []
    for row in rows:
        last = len(row) - 1
        cells = []
        for index, cell in enumerate(row):
            quoted = _quote(cell.strip(), delimiter, auto_quote)
            cells.append(quoted if index == last else quoted.ljust(widths[index]))
        lines.append(separator.join(cells))

    return "\n".join(lines)


class CsvTogglePaddingCommand(sublime_plugin.TextCommand):
    def is_enabled(self):
        return _is_csv_view(self.view)

    def is_visible(self):
        return _is_csv_view(self.view)

    def run(self, edit):
        settings = sublime.load_settings(SETTINGS_FILE)
        delimiter = _choose_delimiter(self.view, settings)
        auto_quote = _view_or_user_setting(self.view, settings, "auto_quote", True)

        whole = sublime.Region(0, self.view.size())
        text = self.view.substr(whole)
        rows = _parse(text, delimiter)
        if not rows:
            return

        expanded = _format_expanded(rows, delimiter, auto_quote)
        already_expanded = text.rstrip("\n") == expanded

        if already_expanded:
            output = _format_compact(rows, delimiter, auto_quote)
        else:
            output = expanded

        if output == text.rstrip("\n"):
            return

        saved_selection = [
            (self.view.rowcol(region.begin()), self.view.rowcol(region.end()))
            for region in self.view.sel()
        ]

        self.view.replace(edit, whole, output)

        self.view.sel().clear()
        for begin_rowcol, end_rowcol in saved_selection:
            begin = self.view.text_point(*begin_rowcol)
            end = self.view.text_point(*end_rowcol)
            self.view.sel().add(sublime.Region(begin, end))


def _cell_span(line, col, delimiter):
    """(start, end) of the field containing column ``col`` within ``line``.

    Splits on ``delimiter`` while respecting double-quoted fields, so a comma
    inside a quoted value does not break the cell. A caret sitting on the
    delimiter (``col`` == its index) belongs to the field it closes.
    """
    spans = []
    start = 0
    index = 0
    length = len(line)
    in_quotes = False
    while index < length:
        char = line[index]
        if char == '"':
            if in_quotes and index + 1 < length and line[index + 1] == '"':
                index += 2
                continue
            in_quotes = not in_quotes
        elif char == delimiter and not in_quotes:
            spans.append((start, index))
            start = index + 1
        index += 1
    spans.append((start, length))

    for begin, end in spans:
        if begin <= col <= end:
            return begin, end
    return spans[-1]


def _cell_value(raw):
    """Logical value of a raw field: trimmed (padding spaces dropped), and if
    quoted, unwrapped with ``""`` unescaped to ``"``."""
    text = raw.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].replace('""', '"')
    return text


class CsvCopyCellCommand(sublime_plugin.TextCommand):
    """Copy the cell under each caret instead of the whole line.

    Bound to the native copy key within ``text.csv`` so cmd+c with no selection
    grabs just the cell. The keybinding only matches when the selection is
    empty, so a real selection falls through to the built-in ``copy``; this
    command defers to it too when invoked (e.g. from the palette) with one.
    """

    def is_enabled(self):
        return _is_csv_view(self.view)

    def run(self, edit):
        view = self.view
        regions = list(view.sel())

        if any(not region.empty() for region in regions):
            view.run_command("copy")
            return

        settings = sublime.load_settings(SETTINGS_FILE)
        delimiter = _choose_delimiter(view, settings)

        values = []
        for region in regions:
            line_region = view.line(region.b)
            col = region.b - line_region.begin()
            line = view.substr(line_region)
            begin, end = _cell_span(line, col, delimiter)
            values.append(_cell_value(line[begin:end]))

        sublime.set_clipboard("\n".join(values))
        count = len(values)
        sublime.status_message(
            "Copied %d cell%s" % (count, "" if count == 1 else "s")
        )
