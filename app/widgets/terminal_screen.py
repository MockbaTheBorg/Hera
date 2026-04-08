# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
IBM 3270 Model 2 terminal screen widget.

Renders an 80×24 data grid plus one OIA (Operator Information Area) status
row at the bottom.  Accepts cell snapshots from Tn3270Session and converts
keyboard events to 3270 action signals consumed by the session thread.

Cell snapshot format (list of 1920 tuples):
    (char: str, fg: QColor, bg: QColor, underscore: bool)

Action types emitted via key_action signal:
    'input'        — bytes: EBCDIC character(s) to insert at cursor
    'aid'          — bytes: single AID byte to transmit
    'tab'          — advance cursor to next unprotected field
    'backtab'      — retreat cursor to previous unprotected field
    'home'         — move cursor to first unprotected field
    'cursor_up/down/left/right' — move cursor one cell
    'backspace'    — delete character and shift field left
    'delete'       — delete character at cursor and shift field left
    'erase_eof'    — erase from cursor to end of field
    'reset'        — unlock keyboard
    'insert_toggle' — toggle insert mode

Additional shortcuts:
    Alt+1 / Alt+2 / Alt+3 — PA1 / PA2 / PA3
    Alt+C                 — Clear
    Alt+R                 — Reset
    Alt+S                 — SysReq
    Alt+A                 — Attn
    Alt+E                 — ErInp
    Alt+D                 — Dup
    Alt+F                 — FldMrk
    PgUp / PgDn           — PF7 / PF8
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QFontMetrics, QGuiApplication
from PySide6.QtCore import Qt, QRect, QSize, QTimer, Signal, Slot

from .terminal_style import DSP3270_FONT_SIZE_PX, terminal_font

# ── IBM 3279 extended colour map ─────────────────────────────────────────────
# Keys are the EBCDIC colour attribute codes; 0x00 means "field default".
COLOR_3279 = {
    0x00: QColor(0x33, 0xFF, 0x33),  # NEUTRAL / no override  → green
    0xf1: QColor(0x33, 0x33, 0xFF),  # BLUE
    0xf2: QColor(0xFF, 0x33, 0x33),  # RED
    0xf3: QColor(0xFF, 0x33, 0xFF),  # PINK
    0xf4: QColor(0x33, 0xFF, 0x33),  # GREEN
    0xf5: QColor(0x33, 0xFF, 0xFF),  # TURQUOISE
    0xf6: QColor(0xFF, 0xFF, 0x33),  # YELLOW
    0xf7: QColor(0xFF, 0xFF, 0xFF),  # WHITE
}

_BG      = QColor(0,   0,   0)
_FG_DEF  = COLOR_3279[0x00]          # default green
_OIA_BG  = QColor(0,   0,  80)       # deep blue bar for OIA
_SEL_BG  = QColor(0x40, 0x60, 0xA0)  # blue highlight for selected cells

ROWS  = 24
COLS  = 80
CELLS = ROWS * COLS


# ── AID byte constants ────────────────────────────────────────────────────────
_AID_ENTER  = 0x7d
_AID_CLEAR  = 0x6d
_AID_PA1    = 0x6c
_AID_PA2    = 0x6e
_AID_PA3    = 0x6b
_AID_SYSREQ = 0xf0   # sent as IAC IP by the session

_PF_AIDS = {
    1:  0xf1, 2:  0xf2, 3:  0xf3, 4:  0xf4,
    5:  0xf5, 6:  0xf6, 7:  0xf7, 8:  0xf8,
    9:  0xf9, 10: 0x7a, 11: 0x7b, 12: 0x7c,
    13: 0xc1, 14: 0xc2, 15: 0xc3, 16: 0xc4,
    17: 0xc5, 18: 0xc6, 19: 0xc7, 20: 0xc8,
    21: 0xc9, 22: 0x4a, 23: 0x4b, 24: 0x4c,
}

# AID keys with a direct 3270 AID byte
_KEY_AID = {
    Qt.Key_Return: _AID_ENTER,
    Qt.Key_Enter:  _AID_ENTER,
    Qt.Key_PageUp: _PF_AIDS[7],
    Qt.Key_PageDown: _PF_AIDS[8],
    Qt.Key_Escape: _PF_AIDS[3],
}

# Non-AID action keys
_KEY_ACTION = {
    Qt.Key_Tab:       'tab',
    Qt.Key_Backtab:   'backtab',
    Qt.Key_Home:      'home',
    Qt.Key_Up:        'cursor_up',
    Qt.Key_Down:      'cursor_down',
    Qt.Key_Left:      'cursor_left',
    Qt.Key_Right:     'cursor_right',
    Qt.Key_Backspace: 'backspace',
    Qt.Key_Delete:    'delete',
    Qt.Key_Insert:    'insert_toggle',
}

_ALT_AID = {
    Qt.Key_1: _AID_PA1,
    Qt.Key_2: _AID_PA2,
    Qt.Key_3: _AID_PA3,
    Qt.Key_C: _AID_CLEAR,
}

_ALT_ACTION = {
    Qt.Key_R: 'reset',
    Qt.Key_S: 'sysreq_attn',
    Qt.Key_A: 'sysreq_attn',
    Qt.Key_E: 'erase_input',
    Qt.Key_D: 'dup',
    Qt.Key_F: 'field_mark',
}

_DEAD_KEY_FALLBACK = {
    Qt.Key_Dead_Acute: "'",
    Qt.Key_Dead_Grave: "`",
    Qt.Key_Dead_Circumflex: "^",
    Qt.Key_Dead_Tilde: "~",
    Qt.Key_Dead_Diaeresis: '"',
}


class TerminalScreen(QWidget):
    """80×24 3270 terminal display with OIA status line (row 25)."""

    # Emitted for every key event that maps to a 3270 action.
    # (action_type: str, data: bytes)
    key_action = Signal(str, bytes)

    def __init__(self, parent=None, *, font_size_px: int = DSP3270_FONT_SIZE_PX):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WA_InputMethodEnabled)

        # Blank initial state: all cells = green space on black
        blank = (' ', _FG_DEF, _BG, False)
        self._cells: list = [blank] * CELLS
        self._cursor_addr: int  = 0
        self._keyboard_locked: bool = True
        self._insert_mode: bool     = False
        self._connected: bool       = False
        self._shift_active: bool    = False
        self._alt_active: bool      = False
        self._capslock_active: bool = False

        # Text selection (cell addresses; None = no selection)
        self._sel_start: int | None = None
        self._sel_end:   int | None = None

        # Cursor blink
        self._cursor_vis: bool = True
        self._blink = QTimer(self)
        self._blink.setInterval(500)
        self._blink.timeout.connect(self._on_blink)
        self._blink.start()

        # Font metrics for cell sizing
        self._font_size_px = font_size_px
        self._apply_font_metrics()

    def _clear_selection(self) -> None:
        self._sel_start = None
        self._sel_end = None

    def _emit_input_bytes(self, data: bytes) -> None:
        if data:
            self.key_action.emit("input", data)

    @staticmethod
    def _encode_printable(text: str) -> bytes:
        batch = bytearray()
        for ch in text:
            if not ch.isprintable():
                continue
            try:
                batch.extend(ch.encode("cp037"))
            except (UnicodeEncodeError, LookupError):
                pass
        return bytes(batch)

    def _emit_clipboard_text(self, text: str) -> None:
        batch = bytearray()
        for ch in text:
            if ch == '\n':
                self._emit_input_bytes(bytes(batch))
                batch.clear()
                self.key_action.emit('aid', bytes([_AID_ENTER]))
                continue
            if ch.isprintable():
                try:
                    batch.extend(ch.encode('cp037'))
                except (UnicodeEncodeError, LookupError):
                    pass
        self._emit_input_bytes(bytes(batch))

    # ── Qt sizing ──────────────────────────────────────────────────────────

    def sizeHint(self) -> QSize:
        return QSize(self._cw * COLS, self._ch * (ROWS + 1) + 4)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_font_size(self, font_size_px: int) -> None:
        if font_size_px == self._font_size_px:
            return
        self._font_size_px = font_size_px
        self._apply_font_metrics()
        self.resize(self.sizeHint())
        self.updateGeometry()
        self.update()

    # ── Public interface ───────────────────────────────────────────────────

    @Slot(list, int, bool, bool)
    def update_screen(self, cells: list, cursor_addr: int,
                      keyboard_locked: bool, insert_mode: bool) -> None:
        """Replace cell data and schedule repaint. Thread-safe via queued signal."""
        self._cells           = cells
        self._cursor_addr     = cursor_addr
        self._keyboard_locked = keyboard_locked
        self._insert_mode     = insert_mode
        self._sel_start       = None   # new screen → stale selection
        self._sel_end         = None
        self.update()

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.update()

    def _set_modifier_state(self, *, mods=None, capslock_active: bool | None = None) -> None:
        changed = False
        if mods is not None:
            shift_active = bool(mods & Qt.ShiftModifier)
            alt_active = bool(mods & Qt.AltModifier)
            if shift_active != self._shift_active:
                self._shift_active = shift_active
                changed = True
            if alt_active != self._alt_active:
                self._alt_active = alt_active
                changed = True
        if capslock_active is not None and capslock_active != self._capslock_active:
            self._capslock_active = capslock_active
            changed = True
        if changed:
            self.update()

    def _modifier_status_text(self) -> str:
        return " ".join(self._modifier_slots())

    def _connection_status_text(self) -> str:
        return "CONN" if self._connected else "DISC"

    def _modifier_slots(self) -> list[str]:
        return [
            "↑" if self._shift_active else " ",
            "INS" if self._insert_mode else "   ",
            "ALT" if self._alt_active else "   ",
            "CAPS" if self._capslock_active else "    ",
        ]

    # ── Painting ───────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setFont(self._font)
        cw, ch, asc = self._cw, self._ch, self._ascent

        sel = self._sel_range()

        for addr in range(CELLS):
            row, col = divmod(addr, COLS)
            x = col * cw
            y = row * ch
            char, fg, bg, us = self._cells[addr]

            # Selection highlight overrides cell background
            if sel is not None and addr in sel:
                bg = _SEL_BG

            # Cursor: invert fg/bg when visible
            if addr == self._cursor_addr and self._cursor_vis:
                fg, bg = bg, fg

            p.fillRect(x, y, cw, ch, bg)
            if char != ' ':
                p.setPen(fg)
                p.drawText(x, y + asc, char)

            if us:
                ul_y = y + ch - 2
                p.setPen(fg)
                p.drawLine(x, ul_y, x + cw - 1, ul_y)

        self._paint_oia(p, ROWS * ch)
        p.end()

    def _paint_oia(self, p: QPainter, oia_y: int) -> None:
        cw, ch, asc = self._cw, self._ch, self._ascent
        total_w = cw * COLS
        metrics = p.fontMetrics()

        p.fillRect(0, oia_y, total_w, ch + 4, _OIA_BG)
        p.setPen(_FG_DEF)
        p.setFont(self._font)

        # Left side: connection / lock / insert state
        parts: list[str] = [self._connection_status_text()]
        if self._connected and self._keyboard_locked:
            parts.append("X SYSTEM")
        left_text = "  ".join(parts)
        p.drawText(4, oia_y + asc, left_text)

        # Right side: cursor row / column (1-based)
        row, col = divmod(self._cursor_addr, COLS)
        pos_text = f"{row + 1:02d}/{col + 1:02d}"
        oia_rect = QRect(0, oia_y, total_w - 4, ch + 4)
        p.drawText(oia_rect, Qt.AlignRight | Qt.AlignVCenter, pos_text)

        # Center: modifier indicators
        modifier_text = self._modifier_status_text()
        left_w = metrics.horizontalAdvance(left_text) + 12
        right_w = metrics.horizontalAdvance(pos_text) + 12
        modifier_w = metrics.horizontalAdvance("↑ INS ALT CAPS") + 8
        center_x = max((total_w - modifier_w) // 2, 0)
        min_x = 4 + left_w
        max_x = total_w - right_w - modifier_w - 4
        if max_x >= min_x:
            center_x = min(max(center_x, min_x), max_x)
        else:
            center_x = min_x
            modifier_w = max(total_w - left_w - right_w - 8, 0)
        if modifier_w > 0:
            modifier_rect = QRect(center_x, oia_y, modifier_w, ch + 4)
            p.drawText(modifier_rect, Qt.AlignLeft | Qt.AlignVCenter, modifier_text)

    def _on_blink(self) -> None:
        self._cursor_vis = not self._cursor_vis
        self.update()

    def _apply_font_metrics(self) -> None:
        self._font = terminal_font(self._font_size_px)
        metrics = QFontMetrics(self._font)
        self._cw = metrics.horizontalAdvance("M")
        self._ch = metrics.height()
        self._ascent = metrics.ascent()

    # ── Selection helpers ──────────────────────────────────────────────────

    def _cell_at(self, pos) -> int:
        """Convert a mouse position to a clamped cell address (0 .. CELLS-1)."""
        col = min(max(pos.x() // self._cw, 0), COLS - 1)
        row = min(max(pos.y() // self._ch, 0), ROWS - 1)
        return row * COLS + col

    def _sel_range(self):
        """Return a range covering the current selection, or None."""
        if self._sel_start is None or self._sel_end is None:
            return None
        lo = min(self._sel_start, self._sel_end)
        hi = max(self._sel_start, self._sel_end)
        return range(lo, hi + 1)

    def _selected_text(self) -> str:
        """Extract selected cells as plain text: trailing spaces stripped per row,
        rows joined with newline, trailing blank lines stripped."""
        sel = self._sel_range()
        if sel is None:
            return ""
        lo, hi = sel.start, sel.stop - 1
        lo_row, lo_col = divmod(lo, COLS)
        hi_row, hi_col = divmod(hi, COLS)
        lines = []
        for row in range(lo_row, hi_row + 1):
            col_start = lo_col if row == lo_row else 0
            col_end   = hi_col if row == hi_row else COLS - 1
            chars = [self._cells[row * COLS + c][0] for c in range(col_start, col_end + 1)]
            lines.append(''.join(chars).rstrip())
        # Strip trailing blank lines
        while lines and not lines[-1]:
            lines.pop()
        return '\n'.join(lines)

    # ── Mouse input ────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            addr = self._cell_at(event.position().toPoint())
            self._sel_start = addr
            self._sel_end   = addr
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self._sel_end = self._cell_at(event.position().toPoint())
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.update()

    # ── Keyboard input ─────────────────────────────────────────────────────

    def focusNextPrevChild(self, next: bool) -> bool:
        """Prevent Qt from using Tab/Shift+Tab for focus navigation.

        Returning False ensures Tab and Shift+Tab are delivered to keyPressEvent
        as 3270 Tab and Backtab actions rather than moving focus to another widget.
        """
        return False

    def keyPressEvent(self, event) -> None:
        key  = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        alt = bool(mods & Qt.AltModifier)
        self._set_modifier_state(mods=mods)

        # Standalone modifier keys do not trigger any action or repeat.
        _MODIFIER_KEYS = (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta,
                          Qt.Key_AltGr, Qt.Key_Super_L, Qt.Key_Super_R)
        if key in _MODIFIER_KEYS:
            return
        if key == Qt.Key_CapsLock:
            self._set_modifier_state(capslock_active=not self._capslock_active)
            return

        # ── Clipboard shortcuts (Ctrl+A / Ctrl+C / Ctrl+V) ─────────────────
        if ctrl and key == Qt.Key_A:
            self._sel_start = 0
            self._sel_end   = CELLS - 1
            self.update()
            return

        if ctrl and key == Qt.Key_C:
            text = self._selected_text()
            if text:
                QGuiApplication.clipboard().setText(text)
            self._clear_selection()
            self.update()
            return

        if ctrl and key == Qt.Key_V:
            self._clear_selection()
            self._emit_clipboard_text(QGuiApplication.clipboard().text())
            self.update()
            return

        # Any other key clears the selection
        if self._sel_start is not None:
            self._clear_selection()
            self.update()

        # F1–F12 → PF1–PF12; Shift+F1–F12 → PF13–PF24
        if Qt.Key_F1 <= key <= Qt.Key_F12:
            pf = key - Qt.Key_F1 + 1
            if mods & Qt.ShiftModifier:
                pf += 12
            self.key_action.emit('aid', bytes([_PF_AIDS[pf]]))
            return

        # Alt shortcuts for common 3270 AID and local actions.
        if alt and not ctrl:
            aid = _ALT_AID.get(key)
            if aid is not None:
                self.key_action.emit('aid', bytes([aid]))
                return

            action = _ALT_ACTION.get(key)
            if action is not None:
                self.key_action.emit(action, b'')
                return

        # AID keys (Enter etc.)
        aid = _KEY_AID.get(key)
        if aid is not None:
            self.key_action.emit('aid', bytes([aid]))
            return

        # Shift+Tab → backtab (Qt delivers Backtab as key value)
        if key == Qt.Key_Tab and (mods & Qt.ShiftModifier):
            self.key_action.emit('backtab', b'')
            return

        # Cursor/editing action keys
        action = _KEY_ACTION.get(key)
        if action is not None:
            self.key_action.emit(action, b'')
            return

        # International keyboard layouts can deliver punctuation keys such as
        # apostrophe as dead keys with no immediate text. In a terminal, the
        # literal character is often the intended result.
        dead_fallback = _DEAD_KEY_FALLBACK.get(key)
        if dead_fallback is not None and not event.text():
            self._emit_input_bytes(self._encode_printable(dead_fallback))
            return

        # Printable character → encode to EBCDIC
        text = event.text()
        if text and text.isprintable():
            self._emit_input_bytes(self._encode_printable(text))
            return

        # Accept and swallow all other unrecognised keys so nothing propagates
        # to parent widgets (the terminal consumes all keyboard input).
        event.accept()

    def keyReleaseEvent(self, event) -> None:
        self._set_modifier_state(mods=event.modifiers())
        event.accept()

    def focusInEvent(self, event) -> None:
        self._set_modifier_state(mods=QGuiApplication.queryKeyboardModifiers())
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self._set_modifier_state(mods=Qt.NoModifier)
        super().focusOutEvent(event)

    def inputMethodEvent(self, event) -> None:
        commit = event.commitString()
        if commit:
            data = self._encode_printable(commit)
            if data:
                self._emit_input_bytes(data)
                self.update()
        event.accept()
