# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Card deck editor widget for Hera card devices.
"""

from typing import Optional

from PySide6.QtCore import Qt, QRect, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QLabel, QScrollBar, QSizePolicy, QWidget

from .card_data import DATA_COLS, SEQ_COLS, TOTAL_COLS, LANGUAGES, pad80, tabs_for_line

_ZONE_GREEN = QColor(240, 255, 240)
_SEL_COLOR = QColor(180, 180, 180)
_TICK_COLOR = QColor(128, 220, 128)


class CardEditorWidget(QWidget):
    """
    80-column constrained card deck editor.
    Internal representation: list[str], each exactly 80 chars.
    Cols 0-71: editable data area.
    Cols 72-79: locked sequence number zone.
    """

    _SCROLLBAR_W = 16
    _STATUS_H = 22
    _FONT_FAMILY = "Courier New"
    _FONT_SIZE = 13

    def __init__(self, read_only: bool = False, auto_number: bool = False, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(400, 200)

        self._read_only = read_only
        self._auto_number = auto_number
        self._lines: list[str] = []
        self._lang = "JCL"
        self._cursor_row = 0
        self._cursor_col = 0
        self._first_row = 0
        self._insert_mode = False
        self._cursor_vis = True
        self._changed = False

        self._sel_anchor: Optional[tuple[int, int]] = None
        self._sel_end: Optional[tuple[int, int]] = None
        self._dragging = False

        self._scrollbar = QScrollBar(Qt.Vertical, self)
        self._scrollbar.setRange(0, 0)
        self._scrollbar.valueChanged.connect(self._on_scroll)

        self._status = QLabel("1:1   OVR", self)
        self._status.setStyleSheet(
            "font-family: 'Courier New', monospace; font-size: 10px;"
            "background: #f0f0f0; border-top: 1px solid #cccccc;"
            "padding: 2px 4px;"
        )

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(530)
        self._blink_timer.timeout.connect(self._blink)
        self._blink_timer.start()

        self._font = QFont(self._FONT_FAMILY, self._FONT_SIZE)
        fm = QFontMetrics(self._font)
        self._cw = fm.horizontalAdvance("M")
        self._ch = fm.height()

    @property
    def lines(self) -> list[str]:
        return self._lines

    @property
    def changed(self) -> bool:
        return self._changed

    @changed.setter
    def changed(self, v: bool):
        self._changed = v

    @property
    def lang(self) -> str:
        return self._lang

    @property
    def cursor_row(self) -> int:
        return self._cursor_row

    def set_language(self, lang: str) -> None:
        if lang in LANGUAGES:
            self._lang = lang
            self.update()

    def set_lines(self, lines: list[str]) -> None:
        self._lines = [pad80(ln) for ln in lines]
        self._refresh_sequence_zone()
        self._cursor_row = 0
        self._cursor_col = 0
        self._first_row = 0
        self._sel_anchor = None
        self._sel_end = None
        self._changed = False
        self._update_scroll_range()
        self.update()

    def append_line(self, line: str) -> None:
        self._lines.append(pad80(line))
        self._refresh_sequence_zone()
        self._update_scroll_range()
        self.update()

    def clear(self) -> None:
        self._lines = []
        self._cursor_row = 0
        self._cursor_col = 0
        self._first_row = 0
        self._sel_anchor = None
        self._sel_end = None
        self._changed = False
        self._update_scroll_range()
        self.update()

    def resizeEvent(self, e):
        sb_w = self._SCROLLBAR_W
        st_h = self._STATUS_H
        self._scrollbar.setGeometry(self.width() - sb_w, 0, sb_w, self.height() - st_h)
        self._status.setGeometry(0, self.height() - st_h, self.width(), st_h)
        self._update_scroll_range()

    def _canvas_rect(self) -> QRect:
        return QRect(0, 0, self.width() - self._SCROLLBAR_W, self.height() - self._STATUS_H)

    @property
    def _visible_rows(self) -> int:
        cr = self._canvas_rect()
        return max(1, cr.height() // self._ch)

    def _update_scroll_range(self):
        total = len(self._lines)
        visible = self._visible_rows
        max_val = max(0, total - visible)
        self._scrollbar.setRange(0, max_val)
        self._scrollbar.setPageStep(visible)
        self._scrollbar.setValue(min(self._first_row, max_val))

    def _on_scroll(self, value: int):
        self._first_row = value
        self.update()

    def wheelEvent(self, e: QWheelEvent):
        steps = -e.angleDelta().y() // 40
        val = max(0, min(self._scrollbar.maximum(), self._first_row + steps))
        self._scrollbar.setValue(val)

    def _ensure_cursor_visible(self):
        if self._cursor_row < self._first_row:
            self._first_row = self._cursor_row
        elif self._cursor_row >= self._first_row + self._visible_rows:
            self._first_row = self._cursor_row - self._visible_rows + 1
        self._first_row = max(0, self._first_row)
        self._scrollbar.setValue(self._first_row)

    def _blink(self):
        if self.hasFocus():
            self._cursor_vis = not self._cursor_vis
            self.update()

    def focusInEvent(self, e):
        self._cursor_vis = True
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._cursor_vis = False
        self.update()
        super().focusOutEvent(e)

    def _update_status(self):
        row = self._cursor_row + 1
        col = self._cursor_col + 1
        mode = "INS" if self._insert_mode else "OVR"
        self._status.setText(f"{row}:{col}   {mode}")

    def _renumber(self):
        if not self._auto_number:
            self._clear_sequence_numbers()
            return
        for i, line in enumerate(self._lines):
            seq = f"{(i + 1) * 10000:08d}"
            self._lines[i] = line[:DATA_COLS].ljust(DATA_COLS) + seq

    def _clear_sequence_numbers(self):
        for i, line in enumerate(self._lines):
            self._lines[i] = line[:DATA_COLS].ljust(DATA_COLS) + (" " * SEQ_COLS)

    def _refresh_sequence_zone(self):
        if self._auto_number:
            self._renumber()
        else:
            self._clear_sequence_numbers()

    def set_auto_number(self, auto_number: bool) -> None:
        self._auto_number = auto_number
        self._refresh_sequence_zone()
        self.update()

    def _has_selection(self) -> bool:
        return (
            self._sel_anchor is not None
            and self._sel_end is not None
            and self._sel_anchor != self._sel_end
        )

    def _normalized_selection(self) -> tuple[tuple[int, int], tuple[int, int]]:
        a = self._sel_anchor
        b = self._sel_end if self._sel_end is not None else a
        a_pos = a[0] * TOTAL_COLS + a[1]
        b_pos = b[0] * TOTAL_COLS + b[1]
        return (a, b) if a_pos <= b_pos else (b, a)

    def _clear_selection(self):
        self._sel_anchor = None
        self._sel_end = None

    def _select_all(self):
        if not self._lines:
            return
        self._sel_anchor = (0, 0)
        self._sel_end = (len(self._lines) - 1, TOTAL_COLS - 1)
        self.update()

    def _copy_selection(self):
        if not self._has_selection():
            return
        start, end = self._normalized_selection()
        rows = []
        for r in range(start[0], end[0] + 1):
            if r >= len(self._lines):
                break
            line = self._lines[r]
            c0 = start[1] if r == start[0] else 0
            c1 = end[1] if r == end[0] else DATA_COLS
            c0 = min(c0, DATA_COLS)
            c1 = min(c1, DATA_COLS)
            rows.append(line[c0:c1].rstrip())
        text = "\n".join(rows).rstrip("\n")
        QGuiApplication.clipboard().setText(text)
        self._clear_selection()
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        cr = self._canvas_rect()
        painter.setClipRect(cr)
        painter.fillRect(cr, Qt.white)

        painter.setFont(self._font)
        n_vis = self._visible_rows

        for vi in range(n_vis + 1):
            li = vi + self._first_row
            y = cr.top() + vi * self._ch
            if y >= cr.bottom():
                break

            line = self._lines[li] if li < len(self._lines) else " " * TOTAL_COLS
            row_rect = QRect(cr.left(), y, cr.width(), self._ch)
            painter.fillRect(row_rect, Qt.white)

            is_jcl = self._is_jcl_line(line)
            self._paint_form_row(painter, row_rect, is_jcl, li < len(self._lines))

            if self._has_selection():
                start, end = self._normalized_selection()
                if start[0] <= li <= end[0]:
                    s_col = start[1] if li == start[0] else 0
                    e_col = end[1] if li == end[0] else TOTAL_COLS
                    s_col = min(s_col, TOTAL_COLS)
                    e_col = min(e_col, TOTAL_COLS)
                    if s_col < e_col:
                        sel_rect = QRect(
                            cr.left() + s_col * self._cw,
                            y,
                            (e_col - s_col) * self._cw,
                            self._ch,
                        )
                        painter.fillRect(sel_rect, _SEL_COLOR)

            painter.setPen(Qt.black)
            fm = QFontMetrics(self._font)
            baseline_y = y + fm.ascent()
            if li < len(self._lines):
                for col_i, ch in enumerate(line[:TOTAL_COLS]):
                    cx = cr.left() + col_i * self._cw
                    painter.drawText(cx, baseline_y, ch)

            if li == self._cursor_row and self._cursor_vis and self.hasFocus():
                cx = cr.left() + self._cursor_col * self._cw
                if self._insert_mode:
                    painter.fillRect(QRect(cx, y, 2, self._ch), Qt.black)
                else:
                    painter.fillRect(QRect(cx, y, self._cw, self._ch), Qt.black)
                    if self._cursor_col < len(line):
                        painter.setPen(Qt.white)
                        painter.drawText(cx, baseline_y, line[self._cursor_col])
                        painter.setPen(Qt.black)

    def _is_jcl_line(self, line: str) -> bool:
        return line.startswith("//") or line.startswith("/*")

    def _effective_lang(self) -> str:
        if self._lang in {"ASM", "FORTRAN", "NONE"}:
            return self._lang
        if self._lang != "JCL":
            return "NONE"

        for raw_line in self._lines[:32]:
            if not raw_line.startswith("//"):
                continue
            card_text = raw_line[2:TOTAL_COLS].rstrip()
            exec_idx = card_text.find(" EXEC ")
            if exec_idx < 0 or exec_idx > 40:
                continue

            program = card_text[exec_idx + 6:].lstrip()
            if program.startswith("PGM="):
                program = program[4:]
            elif program.startswith("PROC="):
                program = program[5:]

            if program.startswith(("IFOX", "IEUASM", "ASM")):
                return "ASM"
            if program.startswith("FORT"):
                return "FORTRAN"

        return "NONE"

    def _form_tick_columns(self, is_jcl: bool) -> set[int]:
        tick_cols = {DATA_COLS}
        effective_lang = self._effective_lang()
        if not is_jcl:
            if effective_lang == "FORTRAN":
                tick_cols.update({5, 6})
            elif effective_lang == "ASM":
                tick_cols.update({8, 9, 14, 15, 71})
        return tick_cols

    def _paint_form_row(
        self,
        painter: QPainter,
        row_rect: QRect,
        is_jcl: bool,
        has_line: bool,
    ) -> None:
        y = row_rect.top()
        row_bottom = row_rect.bottom()

        seq_rect = QRect(
            row_rect.left() + DATA_COLS * self._cw,
            y,
            SEQ_COLS * self._cw,
            self._ch,
        )
        painter.fillRect(seq_rect, _ZONE_GREEN)

        effective_lang = self._effective_lang()
        if not is_jcl:
            if effective_lang == "FORTRAN":
                painter.fillRect(
                    QRect(row_rect.left() + 5 * self._cw + 1, y, self._cw, self._ch),
                    _ZONE_GREEN,
                )
            elif effective_lang == "ASM":
                for col_z in (8, 14):
                    painter.fillRect(
                        QRect(row_rect.left() + col_z * self._cw + 1, y, self._cw, self._ch),
                        _ZONE_GREEN,
                    )

        tick_pen = QPen(_TICK_COLOR, 1)
        painter.setPen(tick_pen)

        left = row_rect.left()
        right = row_rect.left() + TOTAL_COLS * self._cw
        painter.drawLine(left, y, left, row_bottom - 1)
        painter.drawLine(left, row_bottom - 1, right, row_bottom - 1)
        painter.drawLine(right, row_bottom - 1, right, y - 1)

        full_height_cols = self._form_tick_columns(is_jcl)
        tick_top = max(y, row_bottom - 3)
        for col in range(1, TOTAL_COLS):
            x = left + col * self._cw
            if col in full_height_cols:
                painter.drawLine(x, y, x, row_bottom)
            else:
                painter.drawLine(x, tick_top, x, row_bottom)

    def _pos_to_cell(self, pos) -> tuple[int, int]:
        cr = self._canvas_rect()
        x = pos.x() - cr.left()
        y = pos.y() - cr.top()
        col = int(x / self._cw) if self._cw else 0
        row = int(y / self._ch) + self._first_row if self._ch else self._first_row
        col = max(0, min(col, DATA_COLS - 1))
        row = max(0, min(row, max(0, len(self._lines) - 1)))
        return col, row

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            col, row = self._pos_to_cell(e.position())
            self._cursor_row = row
            self._cursor_col = col
            self._sel_anchor = (row, col)
            self._sel_end = None
            self._dragging = True
            self.setFocus()
            self._update_status()
            self.update()

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._dragging and (e.buttons() & Qt.LeftButton):
            col, row = self._pos_to_cell(e.position())
            self._cursor_row = row
            self._cursor_col = col
            self._sel_end = (row, col)
            self._ensure_cursor_visible()
            self._update_status()
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._dragging = False

    def keyPressEvent(self, e: QKeyEvent):
        key = e.key()
        mods = e.modifiers()

        if mods & Qt.ControlModifier:
            if key == Qt.Key_A:
                self._select_all()
            elif key == Qt.Key_C:
                self._copy_selection()
            return

        if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta):
            return

        shift = bool(mods & Qt.ShiftModifier)

        if key in (
            Qt.Key_Left,
            Qt.Key_Right,
            Qt.Key_Up,
            Qt.Key_Down,
            Qt.Key_Home,
            Qt.Key_End,
            Qt.Key_PageUp,
            Qt.Key_PageDown,
        ):
            self._nav_key(key, shift)
            return

        if self._read_only:
            return

        self._clear_selection()

        if key == Qt.Key_Insert:
            self._insert_mode = not self._insert_mode
            self._update_status()
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self._do_enter()
            self._changed = True
        elif key == Qt.Key_Backspace:
            self._do_backspace()
            self._changed = True
        elif key == Qt.Key_Delete:
            self._do_delete()
            self._changed = True
        elif key == Qt.Key_Tab:
            self._do_tab(forward=True)
        elif key == Qt.Key_Backtab:
            self._do_tab(forward=False)
        else:
            text = e.text()
            if text and text.isprintable():
                self._do_type(text[0])
                self._changed = True

        self._ensure_cursor_visible()
        self._update_status()
        self.update()

    def _nav_key(self, key, shift: bool):
        if not shift:
            self._clear_selection()
        elif self._sel_anchor is None:
            self._sel_anchor = (self._cursor_row, self._cursor_col)

        if key == Qt.Key_Left:
            if self._cursor_col > 0:
                self._cursor_col -= 1
        elif key == Qt.Key_Right:
            if self._cursor_col < DATA_COLS - 1:
                self._cursor_col += 1
        elif key == Qt.Key_Up:
            if self._cursor_row > 0:
                self._cursor_row -= 1
        elif key == Qt.Key_Down:
            if self._cursor_row < len(self._lines) - 1:
                self._cursor_row += 1
        elif key == Qt.Key_Home:
            self._cursor_col = 0
        elif key == Qt.Key_End:
            self._cursor_col = DATA_COLS - 1
        elif key == Qt.Key_PageUp:
            self._cursor_row = max(0, self._cursor_row - self._visible_rows)
        elif key == Qt.Key_PageDown:
            self._cursor_row = min(
                max(0, len(self._lines) - 1),
                self._cursor_row + self._visible_rows,
            )

        if shift:
            self._sel_end = (self._cursor_row, self._cursor_col)

        self._ensure_cursor_visible()
        self._update_status()
        self.update()

    def _ensure_one_line(self):
        if not self._lines:
            self._lines = [pad80("")]
            self._refresh_sequence_zone()
            self._update_scroll_range()

    def _do_type(self, char: str):
        self._ensure_one_line()
        row = self._cursor_row
        col = self._cursor_col
        line = self._lines[row]
        data = line[:DATA_COLS]
        seq = line[DATA_COLS:]

        if self._insert_mode:
            new_data = (data[:col] + char + data[col:DATA_COLS - 1])[:DATA_COLS]
        else:
            new_data = data[:col] + char + data[col + 1:]
        self._lines[row] = new_data.ljust(DATA_COLS)[:DATA_COLS] + seq

        if col < DATA_COLS - 1:
            self._cursor_col = col + 1

    def _do_enter(self):
        self._ensure_one_line()
        row = self._cursor_row
        col = self._cursor_col
        line = self._lines[row]
        seq = line[DATA_COLS:]
        data = line[:DATA_COLS]

        left = data[:col].ljust(DATA_COLS)[:DATA_COLS]
        right = data[col:].ljust(DATA_COLS)[:DATA_COLS]

        self._lines[row] = left + seq
        self._lines.insert(row + 1, right + " " * SEQ_COLS)

        self._cursor_row = row + 1
        self._cursor_col = 0
        self._renumber()
        self._update_scroll_range()

    def _do_backspace(self):
        if not self._lines:
            return
        row = self._cursor_row
        col = self._cursor_col

        if col > 0:
            line = self._lines[row]
            data = line[:DATA_COLS]
            seq = line[DATA_COLS:]
            new_data = (data[:col - 1] + data[col:] + " ")[:DATA_COLS]
            self._lines[row] = new_data + seq
            self._cursor_col = col - 1
        elif row > 0:
            prev = self._lines[row - 1]
            curr = self._lines[row]
            prev_data = prev[:DATA_COLS].rstrip()
            curr_data = curr[:DATA_COLS].rstrip()
            if len(prev_data) + len(curr_data) <= DATA_COLS:
                new_data = (prev_data + curr_data).ljust(DATA_COLS)[:DATA_COLS]
                self._lines[row - 1] = new_data + prev[DATA_COLS:]
                del self._lines[row]
                self._cursor_row = row - 1
                self._cursor_col = len(prev_data)
                self._renumber()
                self._update_scroll_range()

    def _do_delete(self):
        if not self._lines:
            return
        row = self._cursor_row
        col = self._cursor_col
        line = self._lines[row]
        data = line[:DATA_COLS]
        seq = line[DATA_COLS:]

        at_content_end = all(c == " " for c in data[col:])

        if not at_content_end:
            new_data = (data[:col] + data[col + 1:] + " ")[:DATA_COLS]
            self._lines[row] = new_data + seq
        elif row < len(self._lines) - 1:
            curr_data = data.rstrip()
            next_line = self._lines[row + 1]
            next_data = next_line[:DATA_COLS].rstrip()
            if len(curr_data) + len(next_data) <= DATA_COLS:
                new_data = (curr_data + next_data).ljust(DATA_COLS)[:DATA_COLS]
                self._lines[row] = new_data + seq
                del self._lines[row + 1]
                self._renumber()
                self._update_scroll_range()

    def _do_tab(self, forward: bool = True):
        if not self._lines:
            return
        line = self._lines[self._cursor_row] if self._cursor_row < len(self._lines) else ""
        tabs = tabs_for_line(line, self._effective_lang())
        col1 = self._cursor_col + 1

        if forward:
            stops = [t for t in tabs if t > col1]
            self._cursor_col = (stops[0] - 1) if stops else (DATA_COLS - 1)
        else:
            stops = [t for t in tabs if t < col1]
            self._cursor_col = (stops[-1] - 1) if stops else 0

        self._cursor_col = max(0, min(self._cursor_col, DATA_COLS - 1))

    def focusNextPrevChild(self, next_: bool) -> bool:
        return False
