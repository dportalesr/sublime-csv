"""
CSV editing commands: toggle padding, copy cell, sort by column, select
column / select by value, move / insert / delete column, clear cell, tab
between cells, shortcuts popup, overtype in padded cells, blank-cell snap
on up/down. Each command's specifics live in its class docstring; the rest
of this docstring covers the padding toggle, whose parsing helpers the
other commands share.

The toggle moves a CSV buffer between its compact source form and a
readable expanded form whose columns are aligned with a `PADDING`-space
gutter on each side of every delimiter, turning the delimiters themselves
into visual column separators:

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
import html
import io
import json

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
    return list(
        csv.reader(
            io.StringIO(text),
            delimiter=delimiter,
            quotechar='"',
            skipinitialspace=True,
        )
    )


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


def _row_spans(line, delimiter):
    """(start, end) spans of every field in ``line``.

    Splits on ``delimiter`` while respecting double-quoted fields, so a comma
    inside a quoted value does not break the cell.
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
    return spans


def _cell_span(line, col, delimiter):
    """(start, end) of the field containing column ``col`` within ``line``.

    A caret sitting on the delimiter (``col`` == its index) belongs to the
    field it closes.
    """
    spans = _row_spans(line, delimiter)
    for begin, end in spans:
        if begin <= col <= end:
            return begin, end
    return spans[-1]


def _column_at(line, col, delimiter):
    """Index of the field containing column ``col``, same ownership rule as
    ``_cell_span``."""
    spans = _row_spans(line, delimiter)
    for index, (begin, end) in enumerate(spans):
        if begin <= col <= end:
            return index
    return len(spans) - 1


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


def _sort_key(value):
    """Orderable key for a logical cell value: numbers sort numerically and
    before strings, strings casefold, empty cells go last (ascending)."""
    if not value:
        return (2, 0.0, "")
    try:
        return (0, float(value), "")
    except ValueError:
        return (1, 0.0, value.casefold())


def _toggle_direction(state, column):
    """Ascending? True on first sort of ``column``; re-sorting the same
    column flips the stored direction."""
    if not state or state.get("column") != column:
        return True
    return not state.get("ascending", True)


def _sort_permutation(lines, column, delimiter, ascending):
    """Row map for the sort: ``result[old_row] == new_row``. Header (row 0)
    and trailing blank lines map to themselves. Stable in both directions,
    so equal keys and identical lines keep their original order."""
    if not lines:
        return []

    trailing_count = 0
    while trailing_count < len(lines) - 1 and lines[-1 - trailing_count] == "":
        trailing_count += 1
    data_end = len(lines) - trailing_count

    def key(old_row):
        line = lines[old_row]
        spans = _row_spans(line, delimiter)
        if column >= len(spans):
            return _sort_key("")
        begin, end = spans[column]
        return _sort_key(_cell_value(line[begin:end]))

    data_rows = list(range(1, data_end))
    data_rows.sort(key=key, reverse=not ascending)

    result = [0] * len(lines)
    for new_row, old_row in enumerate(data_rows, start=1):
        result[old_row] = new_row
    for row in range(data_end, len(lines)):
        result[row] = row
    return result


def _permuted(lines, dest):
    """``lines`` rearranged so line ``old`` lands at row ``dest[old]``."""
    result = [None] * len(lines)
    for old_row, new_row in enumerate(dest):
        result[new_row] = lines[old_row]
    return result


def _sorted_lines(lines, column, delimiter, ascending):
    """Reorder data lines by ``column``'s logical values; the header (line 0)
    and any trailing blank lines stay pinned. Lines move verbatim, so a
    padded buffer stays aligned."""
    if not lines:
        return list(lines)

    return _permuted(lines, _sort_permutation(lines, column, delimiter, ascending))


def _content_bounds(line, span, column):
    """(begin, end) of the trimmed token (quotes included) in the ``column``
    field at ``span``. An empty field gives a bare caret after the delimiter
    gutter, aligning with where content starts in the padded form."""
    begin, end = span
    raw = line[begin:end]
    stripped = raw.strip()
    if stripped:
        content_begin = begin + len(raw) - len(raw.lstrip())
        return content_begin, content_begin + len(stripped)
    anchor = begin if column == 0 else min(begin + PADDING, end)
    return anchor, anchor


def _blank_cell_snap(line, col, delimiter):
    """Where a caret that landed at ``col`` of ``line`` belongs: the content
    start (per ``_content_bounds``) of the cell under it when that cell is
    whitespace-only; None when it has content."""
    column = _column_at(line, col, delimiter)
    span = _row_spans(line, delimiter)[column]
    if line[span[0] : span[1]].strip():
        return None
    return _content_bounds(line, span, column)[0]


def _cell_step(lines, row, col, delimiter, forward):
    """(row, begin, end) of the content (per ``_content_bounds``) of the cell
    after (``forward``) or before the one at ``col`` of ``row``. Past the
    row's end it wraps to the first cell of the next non-blank row, or the
    last cell of the previous one; None at the buffer's edge. ``lines`` only
    needs ``len`` and indexing."""
    line = lines[row]
    spans = _row_spans(line, delimiter)
    column = _column_at(line, col, delimiter) + (1 if forward else -1)
    if not 0 <= column < len(spans):
        step = 1 if forward else -1
        row += step
        while 0 <= row < len(lines) and not lines[row]:
            row += step
        if not 0 <= row < len(lines):
            return None
        line = lines[row]
        spans = _row_spans(line, delimiter)
        column = 0 if forward else len(spans) - 1
    return (row,) + _content_bounds(line, spans[column], column)


def _column_targets(lines, column, delimiter):
    """Per-line ``(row, begin, end)`` selection offsets for ``column``, per
    ``_content_bounds``. Blank lines and rows without the column are
    skipped.
    """
    targets = []
    for row, line in enumerate(lines):
        if not line:
            continue
        spans = _row_spans(line, delimiter)
        if column >= len(spans):
            continue
        targets.append((row,) + _content_bounds(line, spans[column], column))
    return targets


def _value_targets(lines, column, value, delimiter):
    """``_column_targets`` narrowed to cells whose logical value equals
    ``value``; an empty ``value`` targets only the column's empty cells."""
    targets = []
    for row, begin, end in _column_targets(lines, column, delimiter):
        if _cell_value(lines[row][begin:end]) == value:
            targets.append((row, begin, end))
    return targets


def _column_range(lines, region, delimiter):
    """(first, last) column spanned by ``region`` (row_a, col_a, row_b,
    col_b); across rows, the columns between its corners."""
    row_a, col_a, row_b, col_b = region
    return tuple(
        sorted((_column_at(lines[row_a], col_a, delimiter), _column_at(lines[row_b], col_b, delimiter)))
    )


def _column_edit(columns, count, insert):
    """(order, landing) for deleting ``columns`` from a ``count``-column
    table, or with ``insert`` putting one empty column per selected one
    before each run of them. ``order`` is as ``_moved_lines`` takes it (None
    marks a new column); ``landing[column]`` is the new position a caret in
    ``column`` goes to: the column sliding into its place, or the first new
    column of its run."""
    order = []
    landing = {}
    for column in range(count):
        if column not in columns:
            order.append(column)
        elif not insert:
            landing[column] = len(order)
        else:
            if column - 1 not in columns:
                run = 1
                while column + run in columns:
                    run += 1
                start = len(order)
                order.extend([None] * run)
            landing[column] = start
            order.append(column)
    return order, landing


def _landing_col(line, position, delimiter):
    """Content start of the cell at ``position`` of ``line``, or of its last
    cell when the row is shorter."""
    spans = _row_spans(line, delimiter)
    position = min(position, len(spans) - 1)
    return _content_bounds(line, spans[position], position)[0]


def _column_order(columns, count, forward):
    """Old column at each new position once every column in ``columns``
    steps one place right (``forward``) or left in a ``count``-column table;
    adjacent columns move as a block. None when one would pass the edge."""
    order = list(range(count))
    step = 1 if forward else -1
    for column in sorted(columns, reverse=forward):
        target = column + step
        if not 0 <= target < count:
            return None
        order[column], order[target] = order[target], order[column]
    return order


def _moved_lines(lines, order, delimiter):
    """``lines`` with position ``i`` of every row holding old column
    ``order[i]``, or a new empty cell where it is None; columns missing from
    ``order`` are dropped. A row gains empty cells only before one of its
    own; a row left with none becomes blank; blank lines stay. Compact cells
    move verbatim; a padded header means every row is rebuilt aligned, as
    ``_format_expanded`` lays it out."""
    padded = bool(lines) and _is_padded_row(lines[0], delimiter)
    rows = []
    for line in lines:
        cells = [line[begin:end] for begin, end in _row_spans(line, delimiter)] if line else []
        if padded:
            cells = [cell.strip() for cell in cells]
        if cells:
            kept = [new for new, old in enumerate(order) if old is not None and old < len(cells)]
            length = kept[-1] + 1 if kept else 0
            cells = [
                cells[old] if old is not None and old < len(cells) else ""
                for old in order[:length]
            ]
        rows.append(cells)
    if padded:
        return _format_expanded(rows, delimiter, False).split("\n")
    return [delimiter.join(cells) for cells in rows]


def _moved_col(line, moved, col, order, delimiter):
    """Where a caret at ``col`` of ``line`` lands in ``moved``, the same row
    after ``_moved_lines``: same cell, same offset into its content, clamped
    to the content."""
    if not line:
        return col
    old = _column_at(line, col, delimiter)
    begin, _ = _content_bounds(line, _row_spans(line, delimiter)[old], old)
    new = order.index(old)
    new_begin, new_end = _content_bounds(moved, _row_spans(moved, delimiter)[new], new)
    return new_begin + min(max(col - begin, 0), new_end - new_begin)


def _cleared_line(line, columns, delimiter, padded):
    """``line`` with the content of each field in ``columns`` removed; when
    ``padded``, every field but the last turns into spaces instead, keeping
    the delimiters in place."""
    spans = _row_spans(line, delimiter)
    pieces = []
    cursor = 0
    for column, span in enumerate(spans):
        if column not in columns:
            continue
        begin, end = _content_bounds(line, span, column)
        filler = " " * (end - begin) if padded and column < len(spans) - 1 else ""
        pieces += [line[cursor:begin], filler]
        cursor = end
    pieces.append(line[cursor:])
    return "".join(pieces)


def _clear_plan(lines, regions, delimiter):
    """Rows rewritten with every cell a region touches emptied, and one caret
    per region at the content start of its top-left cell. ``regions`` are
    (row_a, col_a, row_b, col_b) in text order; one spanning rows clears the
    rectangle between its corners' columns. A row is padded when it or the
    header is. Returns ({row: line} for rows with cleared cells, [(row,
    col)] in region order)."""
    padded_header = _is_padded_row(lines[0], delimiter)
    cleared = {}
    corners = []
    for region in regions:
        first, last = _column_range(lines, region, delimiter)
        for row in range(region[0], region[2] + 1):
            if lines[row]:
                cleared.setdefault(row, set()).update(range(first, last + 1))
        corners.append((region[0], first))

    rewritten = {}
    for row, columns in cleared.items():
        line = lines[row]
        padded = padded_header or _is_padded_row(line, delimiter)
        rewritten[row] = _cleared_line(line, columns, delimiter, padded)

    carets = []
    for row, column in corners:
        line = rewritten.get(row, lines[row])
        begin, _ = _content_bounds(line, _row_spans(line, delimiter)[column], column)
        carets.append((row, begin))
    return rewritten, carets


def _column_count(lines, delimiter):
    return max((len(_row_spans(line, delimiter)) for line in lines if line), default=0)


def _follow_sort_column(view, order):
    """Keep the remembered ``csv_sort`` column on its column once columns
    are rearranged per ``order``; forget it when that column is gone."""
    state = view.settings().get("csv_sort")
    if not state:
        return
    if state.get("column") in order:
        state["column"] = order.index(state["column"])
        view.settings().set("csv_sort", state)
    else:
        view.settings().erase("csv_sort")


def _select_and_show(view, regions):
    """Replace the selection with ``regions`` and scroll to the first. The
    show repeats on the next tick: right after a whole-buffer replace the
    view scrolls to a stale target."""
    view.sel().clear()
    view.sel().add_all(regions)
    primary = regions[0]
    view.show(primary, animate=False)

    def show_primary():
        if view.is_valid():
            view.show(primary, animate=False)

    sublime.set_timeout(show_primary, 0)


class CsvSortByColumnCommand(sublime_plugin.TextCommand):
    """Sort data rows by the column under the first caret.

    Row 0 is the header and stays pinned. Re-invoking on the same column
    toggles ascending <-> descending (direction is remembered per view in
    the ``csv_sort`` setting); a different column restarts ascending.
    """

    def is_enabled(self):
        return _is_csv_view(self.view)

    def is_visible(self):
        return _is_csv_view(self.view)

    def run(self, edit):
        view = self.view
        if not view.sel():
            return

        settings = sublime.load_settings(SETTINGS_FILE)
        delimiter = _choose_delimiter(view, settings)

        caret = view.sel()[0].b
        line_region = view.line(caret)
        column = _column_at(
            view.substr(line_region), caret - line_region.begin(), delimiter
        )

        ascending = _toggle_direction(view.settings().get("csv_sort"), column)

        whole = sublime.Region(0, view.size())
        text = view.substr(whole)
        lines = text.split("\n")
        dest = _sort_permutation(lines, column, delimiter, ascending)
        output = "\n".join(_permuted(lines, dest))
        if output != text:
            endpoints = [(view.rowcol(r.a), view.rowcol(r.b)) for r in view.sel()]
            view.replace(edit, whole, output)

            regions = [
                sublime.Region(
                    view.text_point(dest[row_a], col_a),
                    view.text_point(dest[row_b], col_b),
                )
                for (row_a, col_a), (row_b, col_b) in endpoints
            ]
            _select_and_show(view, regions)

        view.settings().set("csv_sort", {"column": column, "ascending": ascending})

        header_spans = _row_spans(lines[0], delimiter)
        name = "column %d" % (column + 1)
        if column < len(header_spans):
            begin, end = header_spans[column]
            name = _cell_value(lines[0][begin:end]) or name
        sublime.status_message(
            "Sorted by %s (%s)" % (name, "asc" if ascending else "desc")
        )


class CsvSelectColumnCommand(sublime_plugin.TextCommand):
    """Select every cell of the column(s) under the caret(s).

    Selections cover the trimmed cell token (quotes included); empty cells
    get a bare caret aligned with the padded content start. With multiple
    carets each distinct column is selected.
    """

    def is_enabled(self):
        return _is_csv_view(self.view)

    def is_visible(self):
        return _is_csv_view(self.view)

    def run(self, edit):
        self._select(match_value=False)

    def _select(self, match_value):
        view = self.view
        settings = sublime.load_settings(SETTINGS_FILE)
        delimiter = _choose_delimiter(view, settings)
        lines = view.substr(sublime.Region(0, view.size())).split("\n")

        wanted = []
        for region in view.sel():
            line_region = view.line(region.b)
            line = view.substr(line_region)
            col = region.b - line_region.begin()
            column = _column_at(line, col, delimiter)
            if match_value:
                begin, end = _cell_span(line, col, delimiter)
                key = (column, _cell_value(line[begin:end]))
            else:
                key = column
            if key not in wanted:
                wanted.append(key)

        regions = []
        for key in wanted:
            if match_value:
                targets = _value_targets(lines, key[0], key[1], delimiter)
            else:
                targets = _column_targets(lines, key, delimiter)
            for row, begin, end in targets:
                point = view.text_point(row, 0)
                regions.append(sublime.Region(point + begin, point + end))

        if not regions:
            return
        view.sel().clear()
        for region in regions:
            view.sel().add(region)


class CsvSelectColumnByValueCommand(CsvSelectColumnCommand):
    """Select only the cells of the caret's column whose logical value
    matches the caret cell's (case-sensitive; quoted and bare forms of the
    same value match). On an empty cell, carets spawn only on the column's
    empty cells.
    """

    def run(self, edit):
        self._select(match_value=True)


class CsvMoveColumnCommand(sublime_plugin.TextCommand):
    """Move the column(s) under the caret(s) one step right (``forward``) or
    left across every row. Carets ride along, so repeated presses keep
    carrying the same column. A selection moves every column it spans;
    adjacent columns move as a block; nothing moves past the edge. The
    ``csv_sort`` column follows its column.
    """

    def is_enabled(self):
        return _is_csv_view(self.view)

    def is_visible(self):
        return _is_csv_view(self.view)

    def run(self, edit, forward=True):
        view = self.view
        if not view.sel():
            return

        delimiter = _choose_delimiter(view, sublime.load_settings(SETTINGS_FILE))
        whole = sublime.Region(0, view.size())
        text = view.substr(whole)
        lines = text.split("\n")

        endpoints = [(view.rowcol(r.a), view.rowcol(r.b)) for r in view.sel()]
        columns = set()
        for a, b in endpoints:
            first, last = _column_range(lines, a + b, delimiter)
            columns.update(range(first, last + 1))

        order = _column_order(columns, _column_count(lines, delimiter), forward)
        if order is None:
            sublime.status_message("Column is already %s" % ("last" if forward else "first"))
            return

        moved = _moved_lines(lines, order, delimiter)
        output = "\n".join(moved)
        if output != text:
            view.replace(edit, whole, output)

        def point(row, col):
            return view.text_point(row, _moved_col(lines[row], moved[row], col, order, delimiter))

        _select_and_show(view, [sublime.Region(point(*a), point(*b)) for a, b in endpoints])
        _follow_sort_column(view, order)


class CsvDeleteColumnCommand(sublime_plugin.TextCommand):
    """Delete the column(s) under the caret(s) from every row; a selection
    deletes every column it spans. Each caret lands on the column sliding
    into the gap. The last remaining column stays.
    """

    def is_enabled(self):
        return _is_csv_view(self.view)

    def is_visible(self):
        return _is_csv_view(self.view)

    def run(self, edit):
        self._edit(edit, insert=False)

    def _edit(self, edit, insert):
        view = self.view
        if not view.sel():
            return

        delimiter = _choose_delimiter(view, sublime.load_settings(SETTINGS_FILE))
        whole = sublime.Region(0, view.size())
        text = view.substr(whole)
        lines = text.split("\n")

        columns = set()
        corners = []
        for region in view.sel():
            span = view.rowcol(region.begin()) + view.rowcol(region.end())
            first, last = _column_range(lines, span, delimiter)
            columns.update(range(first, last + 1))
            corners.append((span[0], first))

        order, landing = _column_edit(columns, _column_count(lines, delimiter), insert)
        if not order:
            if not insert:
                sublime.status_message("Can't delete every column")
            return

        edited = _moved_lines(lines, order, delimiter)
        output = "\n".join(edited)
        if output != text:
            view.replace(edit, whole, output)

        _select_and_show(
            view,
            [
                sublime.Region(
                    view.text_point(row, _landing_col(edited[row], landing[column], delimiter))
                )
                for row, column in corners
            ],
        )
        _follow_sort_column(view, order)


class CsvInsertColumnCommand(CsvDeleteColumnCommand):
    """Insert an empty column before the column under each caret, in every
    row; a selection spanning several columns inserts as many before them.
    Carets land in the first new column.
    """

    def run(self, edit):
        self._edit(edit, insert=True)


class CsvClearCellCommand(sublime_plugin.TextCommand):
    """Empty the cell under each caret, or every cell a selection touches (a
    selection spanning rows clears the rectangle between its corners), and
    leave one caret per selection where its first cell's content starts.
    Padded rows keep their delimiters in place, so typing overtypes.
    """

    def is_enabled(self):
        return _is_csv_view(self.view)

    def is_visible(self):
        return _is_csv_view(self.view)

    def run(self, edit):
        view = self.view
        delimiter = _choose_delimiter(view, sublime.load_settings(SETTINGS_FILE))
        lines = view.substr(sublime.Region(0, view.size())).split("\n")
        regions = [view.rowcol(r.begin()) + view.rowcol(r.end()) for r in view.sel()]
        if not regions:
            return

        rewritten, carets = _clear_plan(lines, regions, delimiter)
        for row in sorted(rewritten, reverse=True):
            if rewritten[row] != lines[row]:
                view.replace(edit, view.line(view.text_point(row, 0)), rewritten[row])

        view.sel().clear()
        view.sel().add_all([sublime.Region(view.text_point(row, col)) for row, col in carets])


class _ViewLines:
    """Read-only line sequence over a view that fetches a row only when it is
    indexed, so a keystroke reads just the rows it visits."""

    def __init__(self, view):
        self.view = view
        self.count = view.rowcol(view.size())[0] + 1

    def __len__(self):
        return self.count

    def __getitem__(self, row):
        return self.view.substr(self.view.line(self.view.text_point(row, 0)))


class CsvMoveToCellCommand(sublime_plugin.TextCommand):
    """Spreadsheet-style tab: each caret goes to the next (``forward``) or
    previous cell, wrapping across rows; at the buffer's first or last cell
    it stays. With the ``tab_selects_cell`` setting (default on) it selects
    the cell's content, quotes included, so typing replaces it; off, it
    lands at the content start. A tab-delimited view inserts a tab instead,
    so the delimiter stays typeable.
    """

    def is_enabled(self):
        return _is_csv_view(self.view)

    def is_visible(self):
        return _is_csv_view(self.view)

    def run(self, edit, forward=True):
        view = self.view
        settings = sublime.load_settings(SETTINGS_FILE)
        delimiter = _choose_delimiter(view, settings)
        if delimiter == "\t":
            view.run_command("insert", {"characters": "\t"})
            return

        selects = _view_or_user_setting(view, settings, "tab_selects_cell", True)
        lines = _ViewLines(view)
        regions = []
        for region in view.sel():
            target = _cell_step(lines, *view.rowcol(region.b), delimiter, forward)
            if target is None:
                regions.append(region)
                continue
            row, begin, end = target
            begin_point = view.text_point(row, begin)
            end_point = view.text_point(row, end) if selects else begin_point
            regions.append(sublime.Region(begin_point, end_point))
        if regions:
            view.sel().clear()
            view.sel().add_all(regions)
            view.show(view.sel()[0], animate=False)


PALETTE_PREFIX = "CSV: "
MODIFIER_SYMBOLS = (("ctrl", "⌃"), ("alt", "⌥"), ("shift", "⇧"), ("super", "⌘"))
MODIFIER_ALIASES = {"primary": "super", "command": "super", "option": "alt"}
KEY_SYMBOLS = {
    "backspace": "⌫",
    "delete": "⌦",
    "tab": "⇥",
    "enter": "↩",
    "escape": "⎋",
    "space": "Space",
    "left": "←",
    "right": "→",
    "up": "↑",
    "down": "↓",
    "pageup": "⇞",
    "pagedown": "⇟",
    "home": "↖",
    "end": "↘",
}
SHORTCUTS_STYLE = """
<style>
  body { margin: 0.4rem 0.8rem; }
  .title { font-weight: bold; margin-bottom: 0.4rem; }
  .keys { color: var(--bluish); }
</style>
"""


def _shortcut_rows(keymaps, palette):
    """(keys, caption) per binding in ``keymaps`` (one binding list per
    keymap file) whose command has a ``palette`` entry; the palette is the
    registry, so other packages' ``csv_*`` commands and the overtype
    mechanism stay out. Captions come from the entry with the same command
    and args (else the command's first entry), minus the ``CSV: `` prefix,
    and rows follow palette order. Identical bindings collapse."""
    ranks = {}
    for index, entry in enumerate(palette):
        caption = entry["caption"]
        if caption.startswith(PALETTE_PREFIX):
            caption = caption[len(PALETTE_PREFIX) :]
        args = json.dumps(entry.get("args", {}), sort_keys=True)
        ranks.setdefault((entry["command"], args), (index, caption))
        ranks.setdefault(entry["command"], (index, caption))

    rows = []
    seen = set()
    for keymap in keymaps:
        for binding in keymap:
            command = binding.get("command", "")
            args = json.dumps(binding.get("args", {}), sort_keys=True)
            rank = ranks.get((command, args)) or ranks.get(command)
            identity = (tuple(binding["keys"]), command, args)
            if rank is None or identity in seen:
                continue
            seen.add(identity)
            rows.append(rank + (binding["keys"],))
    rows.sort(key=lambda row: row[:2])
    return [(keys, caption) for _, caption, keys in rows]


def _key_label(keys):
    """macOS menu-style label for a binding's ``keys``: modifiers as ⌃⌥⇧⌘ in
    that order, named keys as symbols, letters upper-cased, chord steps
    space-separated."""
    steps = []
    for step in keys:
        parts = step.split("+")
        modifiers = {MODIFIER_ALIASES.get(part, part) for part in parts[:-1]}
        label = "".join(symbol for name, symbol in MODIFIER_SYMBOLS if name in modifiers)
        steps.append(label + KEY_SYMBOLS.get(parts[-1], parts[-1].upper()))
    return " ".join(steps)


def _shortcuts_html(rows):
    labels = [_key_label(keys) for keys, _ in rows]
    width = max(len(label) for label in labels) + 2
    lines = [
        '<div><span class="keys">%s</span>%s</div>'
        % (html.escape(label) + "&nbsp;" * (width - len(label)), html.escape(caption))
        for label, (_, caption) in zip(labels, rows)
    ]
    return SHORTCUTS_STYLE + '<div class="title">CSV shortcuts</div>' + "".join(lines)


class CsvShowShortcutsCommand(sublime_plugin.TextCommand):
    """Popup at the caret listing the CSV key bindings. Keys are read from
    the loaded keymaps each time, so the list always matches what the keys
    do; labels come from the package's command palette entries."""

    def is_enabled(self):
        return _is_csv_view(self.view)

    def is_visible(self):
        return _is_csv_view(self.view)

    def run(self, edit):
        platform = {"osx": "OSX", "linux": "Linux", "windows": "Windows"}[sublime.platform()]
        names = ("Default.sublime-keymap", "Default (%s).sublime-keymap" % platform)
        keymaps = []
        for path in sublime.find_resources("*.sublime-keymap"):
            if path.rsplit("/", 1)[-1] not in names:
                continue
            text = sublime.load_resource(path)
            if "csv_" not in text:
                continue
            try:
                keymaps.append(sublime.decode_value(text) or [])
            except ValueError:
                continue

        package = __name__.split(".")[0]
        palette = sublime.decode_value(
            sublime.load_resource("Packages/%s/Default.sublime-commands" % package)
        )
        rows = _shortcut_rows(keymaps, palette)
        if not rows:
            sublime.status_message("No CSV shortcuts are bound")
            return
        self.view.show_popup(_shortcuts_html(rows), location=-1, max_width=640, max_height=640)


DELETE_LEFT_RIGHT = "Delete Left Right.sublime-macro"
PAIR_BODIES = {False: "$0", True: "${0:$SELECTION}"}


def _is_padded_row(line, delimiter):
    """True when some delimiter outside quotes has a space on both sides,
    the expanded form's separator."""
    for _, end in _row_spans(line, delimiter)[:-1]:
        if line[end - 1 : end] == " " and line[end + 1 : end + 2] == " ":
            return True
    return False


def _pair_snippet(contents):
    """(open, close, wraps) for snippet contents of the exact shape ``X$0Y``
    (wraps False) or ``X${0:$SELECTION}Y`` (wraps True), X and Y single
    characters; None for anything else."""
    if not isinstance(contents, str):
        return None
    for wraps, body in PAIR_BODIES.items():
        if len(contents) == len(body) + 2 and contents[1:-1] == body:
            return contents[0], contents[-1], wraps
    return None


def _overtype_edits(line, regions, text, delimiter, padded, tail="", keep=False):
    """Each (begin, end) region of ``line`` becomes ``text`` + (its own text
    if ``keep`` else nothing) + ``tail``; its caret column is where ``tail``
    starts. Per touched cell, absorb the net growth with the unbroken run of
    spaces that ends at the closing delimiter and starts no earlier than the
    end of its last region (pre-edit columns): growth > 0 removes up to that
    many from the run, delimiter side first; growth < 0 adds that many back
    before the delimiter when ``padded`` and the delimiter is followed by a
    space or ends the line (an empty last cell whose space was trimmed on
    save). The last cell never absorbs. Returns (edits, carets, absorbed):
    (begin, end, replacement) per touched cell span, ascending; caret column
    per region, input order; spaces removed or added. None when a region
    reaches past its cell (a delimiter inside quotes belongs to the cell) or
    the text it removes holds an odd number of ``"``.
    """
    cells = {}
    for index, (begin, end) in enumerate(regions):
        cell = _cell_span(line, begin, delimiter)
        if end > cell[1] or (not keep and line[begin:end].count('"') % 2):
            return None
        cells.setdefault(cell, []).append(index)

    edits = []
    carets = [None] * len(regions)
    absorbed = 0
    shift = 0
    for cell_begin, cell_end in sorted(cells):
        members = sorted(cells[(cell_begin, cell_end)], key=lambda index: regions[index])
        pieces = []
        length = 0
        cursor = cell_begin
        for index in members:
            begin, end = regions[index]
            for piece in (line[cursor:begin], text, line[begin:end] if keep else ""):
                pieces.append(piece)
                length += len(piece)
            carets[index] = cell_begin + shift + length
            pieces.append(tail)
            length += len(tail)
            cursor = end
        pieces.append(line[cursor:cell_end])
        cell = "".join(pieces)

        growth = len(cell) - (cell_end - cell_begin)
        if cell_end < len(line):
            gap = line[regions[members[-1]][1] : cell_end]
            run = len(gap) - len(gap.rstrip(" "))
            if growth > 0:
                eaten = min(growth, run)
                cell = cell[: len(cell) - eaten]
                absorbed += eaten
            elif growth < 0 and padded and line[cell_end + 1 : cell_end + 2] in (" ", ""):
                cell += " " * -growth
                absorbed -= growth

        edits.append((cell_begin, cell_end, cell))
        shift += len(cell) - (cell_end - cell_begin)
    return edits, carets, absorbed


def _overtype_plan(lines, regions, text, delimiter, delete=None, tail="", keep=False):
    """Whole-keystroke plan. ``lines`` maps row -> text for every region's
    row and row 0; ``regions`` are (row_a, col_a, row_b, col_b). ``delete``
    ("left" / "right" / "pair") turns bare carets into one- or two-character
    regions; a selection is deleted as it is. In a padded row with balanced
    quotes, a bare-caret left / right delete that would take a delimiter, a
    line break or a gutter space (``_at_cell_edge``) stops instead: that
    caret stays and deletes nothing. None (run native) when ``text + tail``
    holds a newline, tab, the delimiter or an odd number of ``"``, any
    region spans lines, any region's row has an odd number of ``"`` (its
    ``_row_spans`` scan ends inside quotes), any other bare-caret delete
    sits at a line boundary, any row's ``_overtype_edits`` is None, or
    nothing is absorbed and no caret stopped. Otherwise ({row: edits},
    [(row, begin, end)] selections, absorbed); a kept selection spans its
    wrapped text, a caret has begin == end.
    """
    inserted = text + tail
    if any(char in inserted for char in ("\n", "\t", delimiter)):
        return None
    if inserted.count('"') % 2:
        return None

    padded_header = _is_padded_row(lines[0], delimiter)
    selections = [None] * len(regions)
    rows = {}
    for position, (row_a, col_a, row_b, col_b) in enumerate(regions):
        if row_a != row_b:
            return None
        begin, end = sorted((col_a, col_b))
        line = lines[row_a]
        if delete and begin == end:
            padded = padded_header or _is_padded_row(line, delimiter)
            if (
                padded
                and line
                and not line.count('"') % 2
                and _at_cell_edge(line, begin, delimiter, delete)
            ):
                selections[position] = (row_a, begin, begin)
                continue
            before, after = {"left": (1, 0), "right": (0, 1), "pair": (1, 1)}[delete]
            begin, end = begin - before, end + after
            if begin < 0 or end > len(line):
                return None
        rows.setdefault(row_a, []).append((position, begin, end))

    edits = {}
    absorbed = 0
    for row, members in rows.items():
        line = lines[row]
        if line.count('"') % 2:
            return None
        padded = padded_header or _is_padded_row(line, delimiter)
        row_regions = [(begin, end) for _, begin, end in members]
        result = _overtype_edits(line, row_regions, text, delimiter, padded, tail, keep)
        if result is None:
            return None
        edits[row], carets, row_absorbed = result
        absorbed += row_absorbed
        for (position, begin, end), caret in zip(members, carets):
            start = caret - (end - begin) if keep else caret
            selections[position] = (row, start, caret)

    stopped = len(regions) - sum(len(members) for members in rows.values())
    if not absorbed and not stopped:
        return None
    return edits, selections, absorbed


def _at_cell_edge(line, col, delimiter, side):
    """True when a one-character delete toward ``side`` ("left" / "right")
    from caret ``col`` would take a delimiter, a line break or the gutter
    space after a delimiter."""
    begin, end = _cell_span(line, col, delimiter)
    gutter = 1 if begin > 0 and line[begin : begin + 1] == " " else 0
    if side == "left":
        return col <= begin + gutter
    if side == "right":
        return col >= end or col < begin + gutter
    return False


def _selection_plan(view, text="", tail="", keep=False, delete=None):
    """``_overtype_plan`` over the live selection, reading only the caret
    rows and row 0."""
    regions = []
    for region in view.sel():
        regions.append(view.rowcol(region.begin()) + view.rowcol(region.end()))
    lines = {}
    for row in {0}.union(region[0] for region in regions):
        lines[row] = view.substr(view.line(view.text_point(row, 0)))
    delimiter = _choose_delimiter(view, sublime.load_settings(SETTINGS_FILE))
    return _overtype_plan(lines, regions, text, delimiter, delete, tail, keep)


def _overtype_args(command_name, args):
    """``csv_overtype`` arguments for a native command it can take over:
    pair snippets, single-character deletes, the empty-pair backspace macro."""
    if command_name == "insert_snippet":
        pair = _pair_snippet(args.get("contents"))
        if pair:
            return {"text": pair[0], "tail": pair[1], "keep": pair[2]}
    elif command_name in ("left_delete", "right_delete"):
        return {"delete": command_name.split("_")[0]}
    elif command_name == "run_macro_file":
        if str(args.get("file", "")).endswith(DELETE_LEFT_RIGHT):
            return {"delete": "pair"}
    return None


class CsvOvertypeCommand(sublime_plugin.TextCommand):
    """Type into padded cells without pushing the closing delimiter.

    Typed characters arrive through the package keymap's ``<character>``
    binding as ``character``; pair snippets and deletes arrive rewritten by
    ``CsvOvertypeListener``. Whatever ``_overtype_plan`` rejects runs as the
    native command instead, so a keystroke is never dropped.
    """

    def run(self, edit, character=None, text="", tail="", keep=False, delete=None):
        view = self.view
        if character is not None:
            text = character
        plan = _selection_plan(view, text, tail, keep, delete)
        if plan is None:
            view.run_command(*self._native(character, text, tail, keep, delete))
            return

        edits, selections, _ = plan
        follow = view.visible_region().contains(view.sel()[0].b)
        for row in sorted(edits, reverse=True):
            start = view.text_point(row, 0)
            for begin, end, cell in reversed(edits[row]):
                view.replace(edit, sublime.Region(start + begin, start + end), cell)

        view.sel().clear()
        view.sel().add_all(
            [
                sublime.Region(view.text_point(row, begin), view.text_point(row, end))
                for row, begin, end in selections
            ]
        )
        if follow:
            view.show(view.sel()[0], animate=False)

    def _native(self, character, text, tail, keep, delete):
        if character is not None:
            return "insert", {"characters": character}
        if delete == "pair":
            return "run_macro_file", {"file": "res://Packages/Default/" + DELETE_LEFT_RIGHT}
        if delete:
            return delete + "_delete", {}
        return "insert_snippet", {"contents": text + PAIR_BODIES[bool(keep)] + tail}


class CsvOvertypeListener(sublime_plugin.EventListener):
    """Answers the ``csv_overtype`` context key that gates the ``<character>``
    binding, and hands pair snippets and deletes in padded cells to
    ``csv_overtype``. Overwrite mode leaves everything native."""

    def on_query_context(self, view, key, operator, operand, match_all):
        if key != "csv_overtype":
            return None
        value = (
            _is_csv_view(view)
            and not view.overwrite_status()
            and _selection_plan(view, "x") is not None
        )
        if operator == sublime.OP_EQUAL:
            return value == operand
        if operator == sublime.OP_NOT_EQUAL:
            return value != operand
        return None

    def on_text_command(self, view, command_name, args):
        if not _is_csv_view(view) or view.overwrite_status():
            return None
        overtype = _overtype_args(command_name, args or {})
        if overtype is None or _selection_plan(view, **overtype) is None:
            return None
        return "csv_overtype", overtype


class CsvBlankCellSnapListener(sublime_plugin.EventListener):
    """An up/down move landing in a whitespace-only cell puts the caret where
    that cell's content starts, and drops its horizontal memory like Home.
    Selections, page moves and horizontal moves stay native."""

    def on_post_text_command(self, view, command_name, args):
        args = args or {}
        if command_name != "move" or args.get("by") != "lines" or args.get("extend"):
            return
        if not _is_csv_view(view):
            return

        delimiter = _choose_delimiter(view, sublime.load_settings(SETTINGS_FILE))
        regions = []
        snapped = False
        for region in view.sel():
            point = None
            if region.empty():
                line_region = view.line(region.b)
                start = line_region.begin()
                col = _blank_cell_snap(view.substr(line_region), region.b - start, delimiter)
                if col is not None and start + col != region.b:
                    point = start + col
            if point is None:
                regions.append(sublime.Region(region.a, region.b, region.xpos))
            else:
                regions.append(sublime.Region(point))
                snapped = True

        if snapped:
            view.sel().clear()
            view.sel().add_all(regions)
