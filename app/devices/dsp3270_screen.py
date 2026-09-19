# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
from typing import Optional

from PySide6.QtGui import QColor

from ..widgets.terminal_screen import COLOR_3279
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
    NUMERIC_ALLOWED_BYTES,
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
    REPLY_MODE_FIELD,
    REPLY_MODE_XFIELD,
    SHORT_READ_AIDS,
    WCC_RESET_BIT,
    WCC_SOUND_ALARM_BIT,
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
    3270 screen model, sized to an arbitrary rows×cols monitor model.

    Maintains the cell array, cursor, keyboard lock state, and current AID.
    Processes host Write commands and formats inbound Read Modified / Read
    Buffer messages.
    """

    def __init__(self, rows: int = 24, cols: int = 80):
        self.rows = rows
        self.cols = cols
        self.cells_count = rows * cols
        self.cells: list[_Cell] = [_Cell() for _ in range(self.cells_count)]
        self.cursor: int = 0
        self.address: int = 0
        self.keyboard_locked: bool = True
        self.current_aid: int = AID_NONE
        # Character-level Set Attribute (SA) state. Per the 3270 data stream
        # architecture this persists across separate Write commands (a host
        # need not re-bracket every partial update) until changed by another
        # SA/SFE/MF order or the buffer is erased. None means "no override in
        # effect for this attribute type" (falls back to the field default).
        self.sa_color: Optional[int] = None
        self.sa_blink: Optional[bool] = None
        self.sa_reverse: Optional[bool] = None
        self.sa_underscore: Optional[bool] = None
        # Reply Mode (Set Reply Mode SF, id 0x09) — governs how Read Modified
        # reports field contents. Resets to Field on connect and on an
        # Erase/Write whose WCC carries the Reset bit (0x40); see write().
        self.reply_mode: int = REPLY_MODE_FIELD

    def erase(self) -> None:
        for c in self.cells:
            c.reset_char()
        self.address = 0
        self.cursor = 0
        self.sa_color = None
        self.sa_blink = None
        self.sa_reverse = None
        self.sa_underscore = None

    def write(self, wcc: int, data: bytes, *, erase: bool = False) -> bool:
        """Process a Write/Erase-Write data stream. Returns True if the WCC
        requests an alarm (bit 0x04) so the caller can sound one; `erase`
        should be True for EW/EWA (and SF_OUTBOUND_DS equivalents) so the
        WCC Reset bit (0x40) can reset Reply Mode back to Field, matching
        how real 3270 firmware scopes that reset to erase commands only."""
        self.address = self.cursor

        if wcc & 0x01:
            for c in self.cells:
                if c.is_attr:
                    c.modified = False
        if wcc & 0x02:
            self.keyboard_locked = False
        if erase and (wcc & WCC_RESET_BIT):
            self.reply_mode = REPLY_MODE_FIELD

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
                        self.sa_color if self.sa_color is not None else fe_color,
                        self.sa_blink if self.sa_blink is not None else fe_blink,
                        self.sa_reverse if self.sa_reverse is not None else fe_reverse,
                        self.sa_underscore if self.sa_underscore is not None else fe_underscore,
                        False,
                        self.sa_color is not None,
                        self.sa_blink is not None,
                        self.sa_reverse is not None,
                        self.sa_underscore is not None,
                    )
                    self.address = wrap_addr(self.address + 1, self.cells_count)

            elif order == ORD_PT:
                here = self.cells[self.address]
                if here.is_attr and not here.prot:
                    self.address = wrap_addr(self.address + 1, self.cells_count)
                else:
                    addr = self._next_unprotected(self.address, forward=True)
                    if addr is None or addr < self.address:
                        addr = 0
                    if (
                        not pt_order_previous_command
                        or (previous_order == ORD_PT and pt_order_previous_null_insert)
                    ):
                        end = wrap_addr(addr - 1, self.cells_count)
                        for a in self._range(self.address, end):
                            if self.cells[a].is_attr:
                                break
                            self._write_char(
                                a,
                                0x00,
                                self.sa_color if self.sa_color is not None else fe_color,
                                self.sa_blink if self.sa_blink is not None else fe_blink,
                                self.sa_reverse if self.sa_reverse is not None else fe_reverse,
                                self.sa_underscore if self.sa_underscore is not None else fe_underscore,
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
                    self.sa_color if self.sa_color is not None else fe_color,
                    self.sa_blink if self.sa_blink is not None else fe_blink,
                    self.sa_reverse if self.sa_reverse is not None else fe_reverse,
                    self.sa_underscore if self.sa_underscore is not None else fe_underscore,
                    True,
                    self.sa_color is not None,
                    self.sa_blink is not None,
                    self.sa_reverse is not None,
                    self.sa_underscore is not None,
                )
                self.address = wrap_addr(self.address + 1, self.cells_count)

            elif order == ORD_SBA:
                self.address = wrap_addr(params[0], self.cells_count)

            elif order == ORD_EUA:
                stop = wrap_addr(params[0], self.cells_count)
                end = wrap_addr(stop - 1, self.cells_count)
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
                self.address = wrap_addr(self.address + 1, self.cells_count)

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
                self.address = wrap_addr(self.address + 1, self.cells_count)

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
                self.address = wrap_addr(self.address + 1, self.cells_count)

            elif order == ORD_SA:
                etype, evalue = params
                sc, sb, sr, su = self._apply_sa_ext(
                    etype,
                    evalue,
                    self.sa_color,
                    self.sa_blink,
                    self.sa_reverse,
                    self.sa_underscore,
                )
                self.sa_color = sc
                self.sa_blink = sb
                self.sa_reverse = sr
                self.sa_underscore = su

            elif order == ORD_RA:
                stop, byte, is_ge = params
                stop = wrap_addr(stop, self.cells_count)
                end = wrap_addr(stop - 1, self.cells_count)
                for a in self._range(self.address, end):
                    self._write_char(
                        a,
                        byte,
                        self.sa_color if self.sa_color is not None else fe_color,
                        self.sa_blink if self.sa_blink is not None else fe_blink,
                        self.sa_reverse if self.sa_reverse is not None else fe_reverse,
                        self.sa_underscore if self.sa_underscore is not None else fe_underscore,
                        is_ge,
                        self.sa_color is not None,
                        self.sa_blink is not None,
                        self.sa_reverse is not None,
                        self.sa_underscore is not None,
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

        return bool(wcc & WCC_SOUND_ALARM_BIT)

    def set_reply_mode(self, mode: int) -> None:
        """Apply a Set Reply Mode structured field (SF id 0x09). Unknown
        mode values are ignored (caller already validates against the three
        defined codes before calling this)."""
        self.reply_mode = mode

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
            if evalue in (0x00, HL_NORMAL):
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
            if evalue in (0x00, HL_NORMAL):
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
            anchor = wrap_addr(start - 1, self.cells_count) if start is not None else self.cursor
            addr = self._next_unprotected(anchor, False)
        if addr is not None:
            self.cursor = addr

    def home(self) -> None:
        addr = self._next_unprotected(0, forward=True)
        self.cursor = addr if addr is not None else 0

    def cursor_move(self, dr: int, dc: int) -> None:
        row, col = divmod(self.cursor, self.cols)
        row = (row + dr) % self.rows
        col = (col + dc) % self.cols
        self.cursor = row * self.cols + col

    def input(self, byte: int, insert: bool = False, allow_any: bool = False) -> None:
        if self.keyboard_locked:
            return
        c = self.cells[self.cursor]
        if c.is_attr or self._is_protected(self.cursor):
            return
        if not allow_any and byte not in NUMERIC_ALLOWED_BYTES and self._is_numeric(self.cursor):
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
        nxt = wrap_addr(self.cursor + 1, self.cells_count)
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
        prev = wrap_addr(self.cursor - 1, self.cells_count)
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
            end = self.cells_count - 1
        for a in self._range(self.cursor, end):
            if self.cells[a].is_attr:
                break
            self.cells[a].byte = 0x00
        self._mark_modified(self.cursor)

    def erase_input(self) -> None:
        for a, c in enumerate(self.cells):
            if not c.is_attr and not self._is_protected(a):
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

    def _is_numeric(self, addr: int) -> bool:
        attr = self._find_attr(addr)
        return attr is not None and attr.num

    def _find_attr(self, addr: int) -> Optional[_Cell]:
        for offset in range(self.cells_count):
            idx = wrap_addr(addr - offset - 1, self.cells_count)
            if self.cells[idx].is_attr:
                return self.cells[idx]
        return None

    def _find_attr_addr(self, addr: int) -> Optional[int]:
        for offset in range(self.cells_count):
            idx = wrap_addr(addr - offset - 1, self.cells_count)
            if self.cells[idx].is_attr:
                return idx
        return None

    def _field_start(self, addr: int) -> Optional[int]:
        attr_addr = self._find_attr_addr(addr)
        if attr_addr is None:
            return None
        return wrap_addr(attr_addr + 1, self.cells_count)

    def _field_end(self, addr: int) -> Optional[int]:
        for offset in range(1, self.cells_count):
            idx = wrap_addr(addr + offset, self.cells_count)
            if self.cells[idx].is_attr:
                return wrap_addr(idx - 1, self.cells_count)
        return None

    def _next_unprotected(self, from_addr: int, forward: bool = True) -> Optional[int]:
        step = 1 if forward else -1
        for offset in range(1, self.cells_count + 1):
            idx = wrap_addr(from_addr + step * offset, self.cells_count)
            c = self.cells[idx]
            if c.is_attr and not c.prot and not c.skip:
                return wrap_addr(idx + 1, self.cells_count)
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

    def _range(self, start: int, end: int):
        if end >= start:
            return range(start, end + 1)
        import itertools
        return itertools.chain(range(start, self.cells_count), range(0, end + 1))

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

        for i in range(self.cells_count):
            c = self.cells[i]
            if c.is_attr and c.modified:
                field_start = wrap_addr(i + 1, self.cells_count)
                out.append(0x11)
                out.extend(encode_addr(field_start))
                out.extend(self._encode_field_readback(field_start, c))

        return bytes(out)

    def _encode_field_readback(self, field_start: int, field_attr: "_Cell") -> bytes:
        """Field content for a Read Modified reply, starting right after its
        attribute byte. Field mode (the default) reports bare character
        bytes, matching prior behavior. Extended-Field mode additionally
        emits SA orders wherever a character's resolved color/highlight
        differs from what was last reported, so a host that explicitly
        negotiated Extended-Field mode gets the extended attributes back.
        (Character mode intentionally falls back to this same field-grouped
        encoding rather than the spec's true per-character form -- real
        hosts under Hercules essentially never request it, and a faithful
        implementation needs an unformatted-screen change-tracking model
        this screen doesn't otherwise maintain.)"""
        extended = self.reply_mode == REPLY_MODE_XFIELD
        out = bytearray()
        last_color = 0x00
        last_reverse = False
        last_underscore = False
        for offset in range(1, self.cells_count):
            a = wrap_addr(field_start + offset - 1, self.cells_count)
            cell = self.cells[a]
            if cell.is_attr:
                break
            if extended:
                color, hl_reverse, hl_us, _ = self._resolve_ext_attrs(cell, field_attr)
                if color != last_color:
                    out.extend((ORD_SA, EAT_COLOR, color))
                    last_color = color
                if hl_reverse != last_reverse or hl_us != last_underscore:
                    hl_value = HL_REVERSE if hl_reverse else HL_UNDERSCORE if hl_us else HL_NORMAL
                    out.extend((ORD_SA, EAT_HIGHLIGHT, hl_value))
                    last_reverse, last_underscore = hl_reverse, hl_us
            if cell.byte != 0x00:
                out.append(cell.byte)
        return bytes(out)

    @staticmethod
    def _resolve_ext_attrs(cell: "_Cell", field_attr: Optional["_Cell"]):
        """Resolve a data cell's effective (color, hl_reverse, hl_underscore,
        hl_blink), inheriting from the owning field's attribute cell
        wherever the data cell itself carries no explicit SA/SFE/MF
        override. Shared by build_snapshot() (rendering) and
        _encode_field_readback() (Extended-Field Read Modified)."""
        color = cell.ext_color
        hl_reverse = cell.hl_reverse
        hl_us = cell.hl_underscore
        hl_blink = cell.hl_blink
        if field_attr is not None:
            if not cell.color_explicit and color == 0x00:
                color = field_attr.ext_color
            if not cell.reverse_explicit and not hl_reverse:
                hl_reverse = field_attr.hl_reverse
            if not cell.underscore_explicit and not hl_us:
                hl_us = field_attr.hl_underscore
            if not cell.blink_explicit and not hl_blink:
                hl_blink = field_attr.hl_blink
        return color, hl_reverse, hl_us, hl_blink

    def build_snapshot(self) -> list:
        """Cell tuples: (char, fg, bg, underscore, blink)."""
        snap = []
        current_attr: Optional[_Cell] = self._find_attr(0)
        for i in range(self.cells_count):
            c = self.cells[i]
            if c.is_attr:
                current_attr = c
                snap.append((' ', _FG_GREEN, _BG_BLACK, False, False))
                continue

            color, hl_reverse, hl_us, hl_blink = self._resolve_ext_attrs(c, current_attr)
            hidden = False

            if current_attr is not None and color == 0x00:
                if current_attr.hidden:
                    hidden = True
                elif current_attr.intensified:
                    color = 0xF7

            if hidden:
                snap.append((' ', _BG_BLACK, _BG_BLACK, False, False))
                continue

            fg = COLOR_3279.get(color, _FG_GREEN)
            bg = _BG_BLACK
            if hl_reverse:
                fg, bg = bg, fg

            snap.append((_cell_to_char(c), fg, bg, hl_us, hl_blink))

        return snap

    def protected_mask(self) -> list[bool]:
        """Per-cell protection state (True = protected/display-only, False =
        an operator-enterable field), single pass like build_snapshot(). Used
        by the scripting API so callers can compute field boundaries instead
        of guessing keystroke/Tab counts."""
        mask = []
        current_attr: Optional[_Cell] = self._find_attr(0)
        for i in range(self.cells_count):
            c = self.cells[i]
            if c.is_attr:
                current_attr = c
                mask.append(False)
                continue
            mask.append(bool(current_attr is not None and current_attr.prot))
        return mask

    def build_text_lines(self, locked: bool = True, insert: bool = False, cursor: int = 0) -> list[str]:
        lines = []
        for row in range(self.rows):
            base = row * self.cols
            line = ''.join(_cell_to_char(self.cells[base + col]) for col in range(self.cols))
            lines.append(line.rstrip())
        # OIA status line (one row past the data grid)
        parts = []
        if locked:
            parts.append("X SYSTEM")
        if insert:
            parts.append("INSERT")
        r, c = divmod(cursor, self.cols)
        status = ("  ".join(parts)).ljust(self.cols - 5) + f"{r+1:02d}/{c+1:02d}"
        lines.append(status)
        return lines
