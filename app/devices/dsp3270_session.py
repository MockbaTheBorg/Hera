# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
import logging
import queue
import socket
import struct
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, Signal

from ..widgets.terminal_screen import ROWS, COLS, CELLS
from .dsp3270_protocol import (
    AID_NONE as _AID_NONE,
    AID_SF as _AID_SF,
    CMD_EAU as _CMD_EAU,
    CMD_EW as _CMD_EW,
    CMD_EWA as _CMD_EWA,
    CMD_NOP as _CMD_NOP,
    CMD_RB as _CMD_RB,
    CMD_RM as _CMD_RM,
    CMD_RMA as _CMD_RMA,
    CMD_W as _CMD_W,
    CMD_WSF as _CMD_WSF,
    DO as _DO,
    DONT as _DONT,
    EOR as _EOR,
    IAC as _IAC,
    IP as _IP,
    OPT_BINARY as _OPT_BINARY,
    OPT_EOR as _OPT_EOR,
    OPT_TTYPE as _OPT_TTYPE,
    ORD_GE as _ORD_GE,
    QC_ALPHA as _QC_ALPHA,
    QC_COLOR as _QC_COLOR,
    QC_HIGHLIGHT as _QC_HIGHLIGHT,
    QC_IMPL_PARTS as _QC_IMPL_PARTS,
    QC_NULL as _QC_NULL,
    QC_REPLY_MODES as _QC_REPLY_MODES,
    QC_SUMMARY as _QC_SUMMARY,
    QC_USABLE as _QC_USABLE,
    QUERY_PROFILE_BODIES as _QUERY_PROFILE_BODIES,
    QUERY_PROFILE_ORDER as _QUERY_PROFILE_ORDER,
    SB as _SB,
    SE as _SE,
    SF_ERASE_RESET as _SF_ERASE_RESET,
    SF_OUTBOUND_DS as _SF_OUTBOUND_DS,
    SF_QUERY_REPLY as _SF_QUERY_REPLY,
    SF_READ_PARTITION as _SF_READ_PARTITION,
    TERMINAL_TYPE as _TERMINAL_TYPE,
    WILL as _WILL,
    WONT as _WONT,
    encode_addr as _encode_addr,
)
from .dsp3270_screen import Screen3270

logger = logging.getLogger(__name__)


class Tn3270Session(QObject):
    """
    TN3270 client running in a daemon thread.

    Emits screen_updated whenever the host sends new screen content.
    Accepts input actions from the UI thread via an internal queue.
    """

    screen_updated = Signal(list, int, bool, bool)
    connected_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._host: str = "127.0.0.1"
        self._port: int = 3270
        self._devnum: str = ""
        self._running: bool = False
        self._connect_enabled: bool = False
        self._is_connected: bool = False
        self._thread: Optional[threading.Thread] = None
        self._input_queue: queue.Queue = queue.Queue()
        self._insert_mode: bool = False
        self._screen = Screen3270()
        self._sock: Optional[socket.socket] = None
        self._buf = bytearray()
        self._iac_buf = bytearray()
        self._records: list[bytes] = []
        self._client_opts: set = set()
        self._host_opts: set = set()
        self._tn3270_ready: bool = False

    def _set_connected(self, connected: bool) -> None:
        if connected == self._is_connected:
            return
        self._is_connected = connected
        self.connected_changed.emit(connected)

    def start(self, host: str, port: int, devnum: str) -> None:
        self._host = host
        self._port = port
        self._devnum = devnum
        self._running = True
        self._connect_enabled = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"Tn3270:{devnum}:{port}"
        )
        self._thread.start()

    def connect_session(self) -> None:
        self._running = True
        self._connect_enabled = True
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._run, daemon=True, name=f"Tn3270:{self._devnum}:{self._port}"
            )
            self._thread.start()

    def disconnect_session(self) -> None:
        self._connect_enabled = False
        self._set_connected(False)
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            finally:
                self._sock = None

    def stop(self) -> None:
        self._running = False
        self._connect_enabled = False
        self._set_connected(False)
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            finally:
                self._sock = None

    def join(self, timeout: float = 1.0) -> None:
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def enqueue_action(self, action: str, data: bytes) -> None:
        self._input_queue.put((action, data))

    def emit_current_screen(self) -> None:
        self._emit_update()

    def _run(self) -> None:
        while self._running:
            if not self._connect_enabled:
                time.sleep(0.1)
                continue
            try:
                self._connect()
                self._set_connected(True)
                self._session_loop()
            except EOFError:
                logger.debug("TN3270 %s:%s - connection closed", self._host, self._port)
            except Exception as exc:
                logger.debug("TN3270 %s:%s - %s", self._host, self._port, exc)
            self._set_connected(False)
            if self._running:
                time.sleep(2.0)

    def _connect(self) -> None:
        self._sock = socket.create_connection((self._host, self._port), timeout=10)
        self._sock.settimeout(None)
        self._buf.clear()
        self._iac_buf.clear()
        self._records.clear()
        self._client_opts.clear()
        self._host_opts.clear()
        self._tn3270_ready = False
        self._negotiate()

    def _negotiate(self) -> None:
        deadline = time.monotonic() + 15.0
        while not self._tn3270_ready and time.monotonic() < deadline:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise EOFError("Connection closed during negotiation")
            for byte in chunk:
                self._feed(byte)
        if not self._tn3270_ready:
            raise Exception("TN3270 negotiation timeout")

    def _is_tn3270_ready(self) -> bool:
        needed_client = {_OPT_BINARY, _OPT_EOR, _OPT_TTYPE}
        needed_host = {_OPT_BINARY, _OPT_EOR}
        return needed_client.issubset(self._client_opts) and needed_host.issubset(self._host_opts)

    def _session_loop(self) -> None:
        self._sock.settimeout(0.005)
        while self._running:
            while not self._input_queue.empty():
                try:
                    action, data = self._input_queue.get_nowait()
                    self._process_action(action, data)
                except queue.Empty:
                    break

            try:
                chunk = self._sock.recv(4096)
                if not chunk:
                    raise EOFError
                for byte in chunk:
                    self._feed(byte)
            except socket.timeout:
                pass

            while self._records:
                record = self._records.pop(0)
                if self._process_record(record):
                    self._emit_update()

    def _feed(self, byte: int) -> None:
        if not self._iac_buf:
            if byte == _IAC:
                self._iac_buf.append(byte)
            else:
                self._buf.append(byte)
            return

        if len(self._iac_buf) == 1:
            if byte == _IAC:
                self._buf.append(_IAC)
                self._iac_buf.clear()
            elif byte == _EOR:
                self._records.append(bytes(self._buf))
                self._buf.clear()
                self._iac_buf.clear()
            elif byte in (_WILL, _WONT, _DO, _DONT, _SB):
                self._iac_buf.append(byte)
            else:
                self._iac_buf.clear()
            return

        cmd = self._iac_buf[1]
        if cmd in (_WILL, _WONT, _DO, _DONT):
            self._handle_negotiation(cmd, byte)
            self._iac_buf.clear()
        elif cmd == _SB:
            if byte == _SE and self._iac_buf[-1] == _IAC:
                payload = bytes(self._iac_buf[2:-1])
                payload = payload.replace(bytes([_IAC, _IAC]), bytes([_IAC]))
                self._handle_subneg(payload)
                self._iac_buf.clear()
            else:
                self._iac_buf.append(byte)

    def _handle_negotiation(self, cmd: int, opt: int) -> None:
        if cmd == _WILL:
            if opt in (_OPT_BINARY, _OPT_EOR):
                self._host_opts.add(opt)
                self._send_raw(bytes([_IAC, _DO, opt]))
            else:
                self._send_raw(bytes([_IAC, _DONT, opt]))
        elif cmd == _WONT:
            self._host_opts.discard(opt)
            self._send_raw(bytes([_IAC, _DONT, opt]))
        elif cmd == _DO:
            if opt in (_OPT_BINARY, _OPT_EOR, _OPT_TTYPE):
                self._client_opts.add(opt)
                self._send_raw(bytes([_IAC, _WILL, opt]))
                if self._is_tn3270_ready():
                    self._tn3270_ready = True
            else:
                self._send_raw(bytes([_IAC, _WONT, opt]))
        elif cmd == _DONT:
            self._client_opts.discard(opt)
            self._send_raw(bytes([_IAC, _WONT, opt]))

    def _handle_subneg(self, payload: bytes) -> None:
        if payload and payload[0] == _OPT_TTYPE and len(payload) >= 2 and payload[1] == 0x01:
            ttype = _TERMINAL_TYPE
            if self._devnum:
                ttype += f"@{self._devnum}"
            encoded = ttype.encode('ascii')
            self._send_raw(bytes([_IAC, _SB, _OPT_TTYPE, 0x00]) + encoded + bytes([_IAC, _SE]))
            if self._is_tn3270_ready():
                self._tn3270_ready = True

    def _send_raw(self, data: bytes) -> None:
        if self._sock:
            try:
                self._sock.sendall(data)
            except Exception as exc:
                logger.debug("Send error: %s", exc)

    def _process_record(self, data: bytes) -> bool:
        if not data:
            return False
        cmd_byte = data[0]

        if cmd_byte in _CMD_EW:
            self._screen.erase()
            self._screen.write(data[1], data[2:])
            return True
        if cmd_byte in _CMD_EWA:
            self._screen.erase()
            self._screen.write(data[1], data[2:])
            return True
        if cmd_byte in _CMD_W:
            self._screen.write(data[1], data[2:])
            return True
        if cmd_byte in _CMD_RB:
            self._send_read_buffer()
            return False
        if cmd_byte in _CMD_RM:
            self._send_3270(self._screen.format_aid_message(self._screen.current_aid))
            return False
        if cmd_byte in _CMD_RMA:
            self._send_3270(self._screen.format_aid_message(self._screen.current_aid, read_all=True))
            return False
        if cmd_byte in _CMD_EAU:
            if self._screen.is_formatted():
                for c in self._screen.cells:
                    if not c.is_attr and not self._screen._is_protected_cell(c):
                        c.byte = 0x00
                        c.modified = False
                for c in self._screen.cells:
                    if c.is_attr and not c.prot:
                        c.modified = False
                addr = self._screen._next_unprotected(0, forward=True)
                self._screen.cursor = addr if addr is not None else 0
            else:
                self._screen.erase()
            self._screen.current_aid = _AID_NONE
            self._screen.keyboard_locked = False
            return True
        if cmd_byte in _CMD_WSF:
            return self._handle_wsf(data[1:])
        if cmd_byte in _CMD_NOP:
            return False

        logger.debug("Unknown 3270 command 0x%02x", cmd_byte)
        return False

    def _send_read_buffer(self) -> None:
        out = bytearray([self._screen.current_aid])
        out.extend(_encode_addr(self._screen.cursor))
        for i in range(CELLS):
            c = self._screen.cells[i]
            if c.is_attr:
                out.append(0x1D)
                out.append(c.byte)
            else:
                if c.is_ge:
                    out.append(_ORD_GE)
                out.append(c.byte)
        self._send_3270(bytes(out))

    def _send_3270(self, data: bytes) -> None:
        escaped = data.replace(bytes([_IAC]), bytes([_IAC, _IAC]))
        self._send_raw(escaped + bytes([_IAC, _EOR]))

    def _handle_wsf(self, data: bytes) -> bool:
        i = 0
        dirty = False
        while i < len(data):
            if i + 2 > len(data):
                break
            length = (data[i] << 8) | data[i + 1]
            if length == 0:
                length = len(data) - i
            if length < 3 or i + length > len(data):
                break
            sf_id = data[i + 2]
            sf_data = data[i + 3 : i + length]
            dirty |= self._process_sf(sf_id, sf_data)
            i += length
        return dirty

    def _process_sf(self, sf_id: int, data: bytes) -> bool:
        if sf_id == _SF_READ_PARTITION:
            if len(data) >= 2:
                ptype = data[1]
                if ptype == 0x02:
                    self._send_query_reply(request_all=True)
                elif ptype == 0x03 and len(data) >= 3:
                    rtype = data[2]
                    codes = list(data[3:]) if len(data) > 3 else []
                    self._send_query_reply(
                        request_all=(rtype == 0x80),
                        codes=codes,
                        equivalent_and_list=(rtype == 0x40),
                    )
            return False
        if sf_id == _SF_ERASE_RESET:
            if data:
                self._screen.erase()
                return True
            return False
        if sf_id == _SF_OUTBOUND_DS:
            if len(data) >= 2:
                cmd = data[1]
                if cmd in (0xF1, 0x01) and len(data) >= 3:
                    self._screen.write(data[2], data[3:])
                    return True
                if cmd in (0xF5, 0x05, 0x7E, 0x0D) and len(data) >= 3:
                    self._screen.erase()
                    self._screen.write(data[2], data[3:])
                    return True
                if cmd in (0x6F, 0x0F):
                    if self._screen.is_formatted():
                        self._screen.erase_input()
                    else:
                        self._screen.erase()
                    self._screen.current_aid = _AID_NONE
                    self._screen.keyboard_locked = False
                    return True
            return False
        return False

    def _send_query_reply(
        self, request_all: bool = True, codes: list | None = None, equivalent_and_list: bool = False
    ) -> None:
        if _TERMINAL_TYPE.endswith("-E"):
            base_supported = list(_QUERY_PROFILE_ORDER)
        else:
            base_supported = [_QC_USABLE, _QC_ALPHA]
        supported = list(base_supported)
        if codes and not request_all:
            if equivalent_and_list:
                supported = list(base_supported)
                for code in codes:
                    if code not in supported:
                        supported.append(code)
            else:
                supported = [c for c in base_supported if c in codes]

        parts = []
        for code in supported:
            body = self._build_query_body(code)
            if body is not None:
                parts.append((code, body))

        if codes is not None and not request_all and not parts:
            parts.append((_QC_NULL, b""))

        summary_codes = bytes([_QC_SUMMARY, _QC_SUMMARY] + [c for (c, _) in parts])
        sf_bytes = self._pack_sf(_SF_QUERY_REPLY, summary_codes)
        for (code, body) in parts:
            sf_bytes += self._pack_sf(_SF_QUERY_REPLY, bytes([code]) + body)

        self._send_3270(bytes([_AID_SF]) + sf_bytes)

    @staticmethod
    def _pack_sf(sf_id: int, data: bytes) -> bytes:
        return struct.pack(">HB", 3 + len(data), sf_id) + data

    def _build_query_body(self, code: int) -> Optional[bytes]:
        profile_body = _QUERY_PROFILE_BODIES.get(code)
        if profile_body is not None:
            return profile_body

        if code == _QC_USABLE:
            return struct.pack(
                ">BBHHBHHHHBBH",
                0x01,
                0x00,
                COLS,
                ROWS,
                0x01,
                10,
                741,
                2,
                111,
                9,
                12,
                CELLS,
            )
        if code == _QC_ALPHA:
            return struct.pack(">BHB", 1, CELLS, 0x00)
        if code == _QC_COLOR:
            reply = struct.pack(">BBBB", 0x00, 8, 0x00, 0xF4)
            for attr in range(0xF1, 0xF8):
                reply += struct.pack(">BB", attr, attr)
            return reply
        if code == _QC_HIGHLIGHT:
            highlights = [0xF1, 0xF2, 0xF4, 0xF8]
            reply = struct.pack(">BBB", len(highlights) + 1, 0x00, 0xF0)
            for hl in highlights:
                reply += struct.pack(">BB", hl, hl)
            return reply
        if code == _QC_REPLY_MODES:
            return struct.pack(">BB", 0x00, 0x01)
        if code == _QC_IMPL_PARTS:
            return struct.pack(">BBHHHH", 0x00, 0x00, ROWS, COLS, ROWS, COLS)
        return None

    def _process_action(self, action: str, data: bytes) -> None:
        s = self._screen

        if action == "aid":
            if not data:
                return
            aid = data[0]
            s.keyboard_locked = True
            s.current_aid = aid
            self._send_3270(s.format_aid_message(aid))
            self._emit_update()
            return

        if action == "sysreq_attn":
            self._send_raw(bytes([_IAC, _IP]))
        elif action == "input":
            for byte in data:
                s.input(byte, insert=self._insert_mode)
        elif action == "tab":
            s.tab(forward=True)
        elif action == "backtab":
            s.tab(forward=False)
        elif action == "home":
            s.home()
        elif action == "cursor_up":
            s.cursor_move(-1, 0)
        elif action == "cursor_down":
            s.cursor_move(1, 0)
        elif action == "cursor_left":
            s.cursor_move(0, -1)
        elif action == "cursor_right":
            s.cursor_move(0, 1)
        elif action == "backspace":
            s.backspace()
        elif action == "delete":
            s.delete()
        elif action == "erase_eof":
            s.erase_eof()
        elif action == "reset":
            s.reset_keyboard()
        elif action == "insert_toggle":
            self._insert_mode = not self._insert_mode
        elif action == "erase_input":
            s.erase_input()
        elif action == "dup":
            s.input(0x1C, insert=False)
            s.tab(forward=True)
        elif action == "field_mark":
            s.input(0x1E, insert=False)

        self._emit_update()

    def _emit_update(self) -> None:
        self.screen_updated.emit(
            self._screen.build_snapshot(),
            self._screen.cursor,
            self._screen.keyboard_locked,
            self._insert_mode,
        )
