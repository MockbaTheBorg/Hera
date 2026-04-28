# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
from typing import Optional

from PySide6.QtGui import QColor

from ..widgets.terminal_screen import COLOR_3279, ROWS, COLS, CELLS
from .dsp3270_protocol import (
    AID_NONE,
    EAT_ALL,
    EAT_COLOR,
    EAT_HIGHLIGHT,
    GE_TO_UNICODE,
    HL_BLINK,
    HL_NORMAL,
    HL_REVERSE,
    HL_UNDERSCORE,
    ORDERS,
    ORD_EUA,
    ORD_GE,
    ORD_IC,
    ORD_MF,
    ORD_PT,
    ORD_RA,
    ORD_SA,
    ORD_SBA,
    ORD_SF,
    ORD_SFE,
    SHORT_READ_AIDS,
    decode_addr,
    ebcdic_to_char,
    encode_addr,
    wrap_addr,
)


def _cell_to_char(cell: "_Cell") -> str:
    if cell.is_attr:
        return ' '
    if cell.is_ge:
        return GE_TO_UNICODE.get(cell.byte, ebcdic_to_char(cell.byte))
    return ebcdic_to_char(cell.byte)


class _Cell:
    """One buffer position in the 3270 screen model."""

    __slots__ = [
        'is_attr',
        'byte',
        'is_ge',
        'prot',
        'num',
        'skip',
        'intensified',
        'hidden',
        'modified',
        'ext_color',
        'hl_blink',
        'hl_reverse',
        'hl_underscore',
        'color_explicit',
        'blink_explicit',
        'reverse_explicit',
        'underscore_explicit',
    ]

    def __init__(self):
        self.is_attr = False
        self.byte = 0x00
        self.is_ge = False
        self.prot = False
        self.num = False
        self.skip = False
        self.intensified = False
        self.hidden = False
        self.modified = False
        self.ext_color = 0x00
        self.hl_blink = False
        self.hl_reverse = False
        self.hl_underscore = False
        self.color_explicit = False
        self.blink_explicit = False
        self.reverse_explicit = False
        self.underscore_explicit = False

    def set_attr_byte(self, attr: int) -> None:
        self.is_attr = True
        self.byte = attr
        self.prot = bool(attr & 0x20)
        self.num = bool(attr & 0x10)
        self.skip = self.prot and self.num
        display = (attr & 0x0C) >> 2
        self.intensified = display == 2
        self.hidden = display == 3
        self.modified = bool(attr & 0x01)

    def reset_char(self) -> None:
        self.is_attr = False
        self.byte = 0x00
        self.is_ge = False
        self.prot = False
        self.num = False
        self.skip = False
        self.intensified = False
        self.hidden = False
        self.modified = False
        self.ext_color = 0x00
        self.hl_blink = False
        self.hl_reverse = False
        self.hl_underscore = False
        self.color_explicit = False
        self.blink_explicit = False
        self.reverse_explicit = False
        self.underscore_explicit = False

    def copy_char_state_from(self, other: "_Cell") -> None:
        self.is_attr = False
        self.byte = other.byte
        self.is_ge = other.is_ge
        self.prot = False
        self.num = False
        self.skip = False
        self.intensified = False
        self.hidden = False
        self.modified = False
        self.ext_color = other.ext_color
        self.hl_blink = other.hl_blink
        self.hl_reverse = other.hl_reverse
        self.hl_underscore = other.hl_underscore
        self.color_explicit = other.color_explicit
        self.blink_explicit = other.blink_explicit
        self.reverse_explicit = other.reverse_explicit
        self.underscore_explicit = other.underscore_explicit


_BG_BLACK = QColor("#000000")
_FG_GREEN = COLOR_3279[0x00]


class Screen3270:
    """
    80x24 3270 screen model.

    Maintains the cell array, cursor, keyboard lock state, and current AID.
    Processes host Write commands and formats inbound Read Modified / Read
    Buffer messages.
    """

    def __init__(self):
        self.cells: list[_Cell] = [_Cell() for _ in range(CELLS)]
        self.cursor: int = 0
        self.address: int = 0
        self.keyboard_locked: bool = True
        self.current_aid: int = AID_NONE

    def erase(self) -> None:
        for c in self.cells:
            c.reset_char()
        self.address = 0
        self.cursor = 0

    def write(self, wcc: int, data: bytes) -> None:
        self.address = self.cursor

        if wcc & 0x01:
            for c in self.cells:
                if c.is_attr:
                    c.modified = False
        if wcc & 0x02:
            self.keyboard_locked = False

        sa_color = None
        sa_blink = None
        sa_reverse = None
        sa_underscore = None

        fe_color = 0x00
        fe_blink = False
        fe_reverse = False
        fe_underscore = False

        previous_order = object()
        pt_order_previous_command = True
        pt_order_previous_null_insert = False

        for (order, params) in self._parse_orders(data):
            if order is None:
                for byte in params:
                    self._write_char(
                        self.address,
                        byte,
                        sa_color if sa_color is not None else fe_color,
                        sa_blink if sa_blink is not None else fe_blink,
                        sa_reverse if sa_reverse is not None else fe_reverse,
                        sa_underscore if sa_underscore is not None else fe_underscore,
                        False,
                        sa_color is not None,
                        sa_blink is not None,
                        sa_reverse is not None,
                        sa_underscore is not None,
                    )
                    self.address = wrap_addr(self.address + 1)

            elif order == ORD_PT:
                here = self.cells[self.address]
                if here.is_attr and not here.prot:
                    self.address = wrap_addr(self.address + 1)
                else:
                    addr = self._next_unprotected(self.address, forward=True)
                    if addr is None or addr < self.address:
                        addr = 0
                    if (
                        not pt_order_previous_command
                        or (previous_order == ORD_PT and pt_order_previous_null_insert)
                    ):
                        end = wrap_addr(addr - 1)
                        for a in self._range(self.address, end):
                            if self.cells[a].is_attr:
                                break
                            self._write_char(
                                a,
                                0x00,
                                sa_color if sa_color is not None else fe_color,
                                sa_blink if sa_blink is not None else fe_blink,
                                sa_reverse if sa_reverse is not None else fe_reverse,
                                sa_underscore if sa_underscore is not None else fe_underscore,
                                False,
                            )
                        pt_order_previous_null_insert = addr == 0
                    else:
                        pt_order_previous_null_insert = False
                    self.address = addr

            elif order == ORD_GE:
                self._write_char(
                    self.address,
                    params[0],
                    sa_color if sa_color is not None else fe_color,
                    sa_blink if sa_blink is not None else fe_blink,
                    sa_reverse if sa_reverse is not None else fe_reverse,
                    sa_underscore if sa_underscore is not None else fe_underscore,
                    True,
                    sa_color is not None,
                    sa_blink is not None,
                    sa_reverse is not None,
                    sa_underscore is not None,
                )
                self.address = wrap_addr(self.address + 1)

            elif order == ORD_SBA:
                self.address = params[0]

            elif order == ORD_EUA:
                stop = params[0]
                end = wrap_addr(stop - 1)
                for a in self._range(self.address, end):
                    if not self.cells[a].is_attr and not self._is_protected(a):
                        self.cells[a].byte = 0x00
                self.address = stop

            elif order == ORD_IC:
                self.cursor = self.address

            elif order == ORD_SF:
                attr_byte = params[0]
                c = self.cells[self.address]
                c.set_attr_byte(attr_byte)
                c.ext_color = 0x00
                c.hl_blink = False
                c.hl_reverse = False
                c.hl_underscore = False
                fe_color = fe_blink = 0x00
                fe_reverse = fe_underscore = False
                self.address = wrap_addr(self.address + 1)

            elif order == ORD_SFE:
                attr_byte, ext_list = params
                c = self.cells[self.address]
                c.set_attr_byte(attr_byte if attr_byte is not None else 0x00)
                fe_color, fe_blink, fe_reverse, fe_underscore = 0x00, False, False, False
                for (etype, evalue) in ext_list:
                    fc, fb, fr, fu = self._apply_field_ext(
                        etype, evalue, fe_color, fe_blink, fe_reverse, fe_underscore
                    )
                    fe_color, fe_blink, fe_reverse, fe_underscore = fc, fb, fr, fu
                c.ext_color = fe_color
                c.hl_blink = fe_blink
                c.hl_reverse = fe_reverse
                c.hl_underscore = fe_underscore
                self.address = wrap_addr(self.address + 1)

            elif order == ORD_MF:
                attr_byte, ext_list = params
                c = self.cells[self.address]
                if c.is_attr:
                    if attr_byte is not None:
                        c.set_attr_byte(attr_byte)
                    for (etype, evalue) in ext_list:
                        fc, fb, fr, fu = self._apply_field_ext(
                            etype, evalue, c.ext_color, c.hl_blink, c.hl_reverse, c.hl_underscore
                        )
                        c.ext_color, c.hl_blink, c.hl_reverse, c.hl_underscore = fc, fb, fr, fu
                self.address = wrap_addr(self.address + 1)

            elif order == ORD_SA:
                etype, evalue = params
                sc, sb, sr, su = self._apply_sa_ext(
                    etype,
                    evalue,
                    sa_color,
                    sa_blink,
                    sa_reverse,
                    sa_underscore,
                )
                sa_color = sc
                sa_blink = sb
                sa_reverse = sr
                sa_underscore = su

            elif order == ORD_RA:
                stop, byte, is_ge = params
                end = wrap_addr(stop - 1)
                for a in self._range(self.address, end):
                    self._write_char(
                        a,
                        byte,
                        sa_color if sa_color is not None else fe_color,
                        sa_blink if sa_blink is not None else fe_blink,
                        sa_reverse if sa_reverse is not None else fe_reverse,
                        sa_underscore if sa_underscore is not None else fe_underscore,
                        is_ge,
                        sa_color is not None,
                        sa_blink is not None,
                        sa_reverse is not None,
                        sa_underscore is not None,
                    )
                self.address = stop

            if order is not None and order != ORD_GE:
                pt_order_previous_command = True
            else:
                pt_order_previous_command = False
            previous_order = order

        if wcc & 0x02:
            self.keyboard_locked = False
            self.current_aid = AID_NONE

    def _write_char(
        self,
        addr: int,
        byte: int,
        color: int,
        blink: bool,
        reverse: bool,
        underscore: bool,
        is_ge: bool = False,
        explicit_color: bool = False,
        explicit_blink: bool = False,
        explicit_reverse: bool = False,
        explicit_underscore: bool = False,
        preserve_previous_explicit: bool = False,
    ) -> None:
        previous = self.cells[addr]
        previous_ext_color = previous.ext_color
        previous_hl_blink = previous.hl_blink
        previous_hl_reverse = previous.hl_reverse
        previous_hl_underscore = previous.hl_underscore
        previous_color_explicit = previous.color_explicit
        previous_blink_explicit = previous.blink_explicit
        previous_reverse_explicit = previous.reverse_explicit
        previous_underscore_explicit = previous.underscore_explicit
        c = self.cells[addr]
        c.reset_char()
        c.byte = byte
        c.is_ge = is_ge
        if explicit_color:
            c.ext_color = color
            c.color_explicit = True
        elif preserve_previous_explicit and previous_color_explicit:
            c.ext_color = previous_ext_color
            c.color_explicit = True

        if explicit_blink:
            c.hl_blink = blink
            c.blink_explicit = True
        elif preserve_previous_explicit and previous_blink_explicit:
            c.hl_blink = previous_hl_blink
            c.blink_explicit = True

        if explicit_reverse:
            c.hl_reverse = reverse
            c.reverse_explicit = True
        elif preserve_previous_explicit and previous_reverse_explicit:
            c.hl_reverse = previous_hl_reverse
            c.reverse_explicit = True

        if explicit_underscore:
            c.hl_underscore = underscore
            c.underscore_explicit = True
        elif preserve_previous_explicit and previous_underscore_explicit:
            c.hl_underscore = previous_hl_underscore
            c.underscore_explicit = True

    @staticmethod
    def _apply_field_ext(
        etype: int, evalue: int, color: int, blink: bool, reverse: bool, underscore: bool
    ):
        if etype == EAT_ALL:
            return 0x00, False, False, False
        if etype == EAT_COLOR:
            return evalue, blink, reverse, underscore
        if etype == EAT_HIGHLIGHT:
            if evalue == HL_NORMAL:
                return color, False, False, False
            if evalue == HL_BLINK:
                return color, True, False, False
            if evalue == HL_REVERSE:
                return color, False, True, False
            if evalue == HL_UNDERSCORE:
                return color, False, False, True
        return color, blink, reverse, underscore

    @staticmethod
    def _apply_sa_ext(
        etype: int,
        evalue: int,
        color: Optional[int],
        blink: Optional[bool],
        reverse: Optional[bool],
        underscore: Optional[bool],
    ):
        if etype == EAT_ALL:
            return None, None, None, None
        if etype == EAT_COLOR:
            return (None if evalue == 0x00 else evalue), blink, reverse, underscore
        if etype == EAT_HIGHLIGHT:
            if evalue == HL_NORMAL:
                return color, None, None, None
            if evalue == HL_BLINK:
                return color, True, False, False
            if evalue == HL_REVERSE:
                return color, False, True, False
            if evalue == HL_UNDERSCORE:
                return color, False, False, True
        return color, blink, reverse, underscore

    @staticmethod
    def _parse_orders(data: bytes):
        i = 0
        pending = bytearray()

        while i < len(data):
            b = data[i]

            if b not in ORDERS:
                if b == 0x00 or 0x40 <= b <= 0xFE:
                    pending.append(b)
                i += 1
                continue

            if pending:
                yield (None, bytes(pending))
                pending = bytearray()

            i += 1

            if b == ORD_PT:
                yield (ORD_PT, None)
            elif b == ORD_GE:
                yield (ORD_GE, [data[i]])
                i += 1
            elif b == ORD_SBA:
                addr = decode_addr(data[i], data[i + 1])
                yield (ORD_SBA, [addr])
                i += 2
            elif b == ORD_EUA:
                addr = decode_addr(data[i], data[i + 1])
                yield (ORD_EUA, [addr])
                i += 2
            elif b == ORD_IC:
                yield (ORD_IC, None)
            elif b == ORD_SF:
                yield (ORD_SF, [data[i]])
                i += 1
            elif b == ORD_SA:
                yield (ORD_SA, (data[i], data[i + 1]))
                i += 2
            elif b in (ORD_SFE, ORD_MF):
                count = data[i]
                i += 1
                attr_byte = None
                ext_list = []
                for _ in range(count):
                    atype = data[i]
                    avalue = data[i + 1]
                    i += 2
                    if atype == 0xC0:
                        attr_byte = avalue
                    else:
                        ext_list.append((atype, avalue))
                yield (b, (attr_byte, ext_list))
            elif b == ORD_RA:
                stop = decode_addr(data[i], data[i + 1])
                i += 2
                is_ge = i < len(data) and data[i] == ORD_GE
                if is_ge:
                    i += 1
                rep_byte = data[i]
                i += 1
                yield (ORD_RA, (stop, rep_byte, is_ge))

        if pending:
            yield (None, bytes(pending))

    def is_formatted(self) -> bool:
        return any(c.is_attr for c in self.cells)

    def tab(self, forward: bool = True) -> None:
        if forward:
            addr = self._next_unprotected(self.cursor, True)
        else:
            start = self._field_start(self.cursor)
            anchor = wrap_addr(start - 1) if start is not None else self.cursor
            addr = self._next_unprotected(anchor, False)
        if addr is not None:
            self.cursor = addr

    def home(self) -> None:
        addr = self._next_unprotected(0, forward=True)
        self.cursor = addr if addr is not None else 0

    def cursor_move(self, dr: int, dc: int) -> None:
        row, col = divmod(self.cursor, COLS)
        row = (row + dr) % ROWS
        col = (col + dc) % COLS
        self.cursor = row * COLS + col

    def input(self, byte: int, insert: bool = False) -> None:
        if self.keyboard_locked:
            return
        c = self.cells[self.cursor]
        if c.is_attr or self._is_protected(self.cursor):
            return
        if insert:
            end = self._field_end(self.cursor)
            if end is not None:
                self._shift_right(self.cursor, end)
        self._write_char(
            self.cursor,
            byte,
            0x00,
            False,
            False,
            False,
            preserve_previous_explicit=True,
        )
        self._mark_modified(self.cursor)
        nxt = wrap_addr(self.cursor + 1)
        if self.cells[nxt].is_attr:
            ahead = self._next_unprotected(nxt, forward=True)
            if ahead is not None:
                nxt = ahead
        self.cursor = nxt

    def backspace(self) -> None:
        if self._is_protected(self.cursor):
            return
        start = self._field_start(self.cursor)
        if start is None or self.cursor == start:
            return
        prev = wrap_addr(self.cursor - 1)
        end = self._field_end(self.cursor)
        if end is not None:
            self._shift_left(prev, end)
        self._mark_modified(prev)
        self.cursor = prev

    def delete(self) -> None:
        if self._is_protected(self.cursor):
            return
        end = self._field_end(self.cursor)
        if end is not None:
            self._shift_left(self.cursor, end)
        self._mark_modified(self.cursor)

    def erase_eof(self) -> None:
        if self._is_protected(self.cursor):
            return
        end = self._field_end(self.cursor)
        if end is None:
            end = CELLS - 1
        for a in self._range(self.cursor, end):
            if self.cells[a].is_attr:
                break
            self.cells[a].byte = 0x00
        self._mark_modified(self.cursor)

    def erase_input(self) -> None:
        for c in self.cells:
            if not c.is_attr and not self._is_protected_cell(c):
                c.byte = 0x00
                c.modified = False
        for c in self.cells:
            if c.is_attr and not c.prot:
                c.modified = False
        addr = self._next_unprotected(0, forward=True)
        self.cursor = addr if addr is not None else 0

    def reset_keyboard(self) -> None:
        self.keyboard_locked = False

    def _is_protected(self, addr: int) -> bool:
        attr = self._find_attr(addr)
        return attr is not None and attr.prot

    @staticmethod
    def _is_protected_cell(c: _Cell) -> bool:
        return c.is_attr or c.prot

    def _find_attr(self, addr: int) -> Optional[_Cell]:
        for offset in range(CELLS):
            idx = wrap_addr(addr - offset - 1)
            if self.cells[idx].is_attr:
                return self.cells[idx]
        return None

    def _find_attr_addr(self, addr: int) -> Optional[int]:
        for offset in range(CELLS):
            idx = wrap_addr(addr - offset - 1)
            if self.cells[idx].is_attr:
                return idx
        return None

    def _field_start(self, addr: int) -> Optional[int]:
        attr_addr = self._find_attr_addr(addr)
        if attr_addr is None:
            return None
        return wrap_addr(attr_addr + 1)

    def _field_end(self, addr: int) -> Optional[int]:
        for offset in range(1, CELLS):
            idx = wrap_addr(addr + offset)
            if self.cells[idx].is_attr:
                return wrap_addr(idx - 1)
        return None

    def _next_unprotected(self, from_addr: int, forward: bool = True) -> Optional[int]:
        step = 1 if forward else -1
        for offset in range(1, CELLS + 1):
            idx = wrap_addr(from_addr + step * offset)
            c = self.cells[idx]
            if c.is_attr and not c.prot and not c.skip:
                return wrap_addr(idx + 1)
        return None

    def _mark_modified(self, addr: int) -> None:
        attr_addr = self._find_attr_addr(addr)
        if attr_addr is not None:
            self.cells[attr_addr].modified = True

    def _shift_left(self, start: int, end: int) -> None:
        addrs = list(self._range(start, end))
        for l, r in zip(addrs, addrs[1:]):
            self.cells[l].copy_char_state_from(self.cells[r])
        self.cells[end].reset_char()

    def _shift_right(self, start: int, end: int) -> None:
        addrs = list(self._range(start, end))
        for l, r in reversed(list(zip(addrs, addrs[1:]))):
            self.cells[r].copy_char_state_from(self.cells[l])
        self.cells[start].reset_char()

    @staticmethod
    def _range(start: int, end: int):
        if end >= start:
            return range(start, end + 1)
        import itertools
        return itertools.chain(range(start, CELLS), range(0, end + 1))

    def format_aid_message(self, aid: int, read_all: bool = False) -> bytes:
        if aid in SHORT_READ_AIDS and not read_all:
            return bytes([aid])

        out = bytearray([aid])
        out.extend(encode_addr(self.cursor))

        if not self.is_formatted():
            raw = bytearray()
            for c in self.cells:
                if not c.is_attr:
                    raw.append(c.byte)
            out.extend(raw)
            return bytes(out)

        for i in range(CELLS):
            c = self.cells[i]
            if c.is_attr and c.modified:
                field_start = wrap_addr(i + 1)
                field_bytes = bytearray()
                for offset in range(1, CELLS):
                    a = wrap_addr(field_start + offset - 1)
                    cell = self.cells[a]
                    if cell.is_attr:
                        break
                    if cell.byte != 0x00:
                        field_bytes.append(cell.byte)
                out.append(0x11)
                out.extend(encode_addr(field_start))
                out.extend(field_bytes)

        return bytes(out)

    def build_snapshot(self) -> list:
        snap = []
        current_attr: Optional[_Cell] = self._find_attr(0)
        for i in range(CELLS):
            c = self.cells[i]
            if c.is_attr:
                current_attr = c
                snap.append((' ', _FG_GREEN, _BG_BLACK, False))
                continue

            color = c.ext_color
            hl_reverse = c.hl_reverse
            hl_us = c.hl_underscore
            hidden = False

            if current_attr is not None:
                if not c.color_explicit and color == 0x00:
                    color = current_attr.ext_color
                if not c.reverse_explicit and not hl_reverse:
                    hl_reverse = current_attr.hl_reverse
                if not c.underscore_explicit and not hl_us:
                    hl_us = current_attr.hl_underscore
                if color == 0x00:
                    if current_attr.hidden:
                        hidden = True
                    elif current_attr.intensified:
                        color = 0xF7

            if hidden:
                snap.append((' ', _BG_BLACK, _BG_BLACK, False))
                continue

            fg = COLOR_3279.get(color, _FG_GREEN)
            bg = _BG_BLACK
            if hl_reverse:
                fg, bg = bg, fg

            snap.append((_cell_to_char(c), fg, bg, hl_us))

        return snap

    def build_text_lines(self, locked: bool = True, insert: bool = False, cursor: int = 0) -> list[str]:
        lines = []
        for row in range(ROWS):
            base = row * COLS
            line = ''.join(_cell_to_char(self.cells[base + col]) for col in range(COLS))
            lines.append(line.rstrip())
        # Row 25 — OIA status line
        parts = []
        if locked:
            parts.append("X SYSTEM")
        if insert:
            parts.append("INSERT")
        r, c = divmod(cursor, COLS)
        status = ("  ".join(parts)).ljust(COLS - 5) + f"{r+1:02d}/{c+1:02d}"
        lines.append(status)
        return lines
