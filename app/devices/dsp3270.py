# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Hera IBM 3270 display terminal device plugin.

Handles devclass="DSP" — IBM 3270 Model 2 (80×24) terminals.

This module contains the device wrapper only.
The TN3270 implementation is split across:
  - `dsp3270_protocol.py` for protocol constants and helpers
  - `dsp3270_screen.py` for the 3270 screen model
  - `dsp3270_session.py` for the threaded TN3270 client/session

Connection model
----------------
A daemon thread (Tn3270Session) opens a TCP connection to the Hercules TN3270
listener port (obtained from api_client.get_console_port()).  Telnet option
negotiation (BINARY + EOR + TTYPE) is performed synchronously at connect time.
The device CUU is appended to the terminal-type string so Hercules routes the
connection to the correct virtual 3270 device.

Data flows
----------
Host → terminal : records processed in the session thread; a Screen3270 model
                  is updated; a cell snapshot is emitted to the UI via signal.
Terminal → host : key actions are placed on a queue by the UI thread;
                  the session thread drains them and sends the formatted
                  3270 inbound message to the host.
"""

import logging
from typing import Optional

import shiboken6
from PySide6.QtCore import Slot, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..device_base import DeviceBase, ButtonDef, DeviceContext
from ..theme import WORKSPACE_FRAME
from ..widgets.mini_screen import MiniScreenOverlay
from ..widgets.terminal_screen import ROWS, COLS, _FG_DEF, _OIA_BG
from ..widgets.terminal_style import DSP3270_FONT_SIZE_PX, terminal_font_family
from .dsp3270_session import Tn3270Session

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Device plugin
# ═══════════════════════════════════════════════════════════════════════════════

# Mini-screen position within 3270.png (from Jason Device.cpp reference table)
_MINI_X = 21
_MINI_Y = 7
_MINI_W = 76
_MINI_H = 55
_MINI_OPACITY = 0.5   # 0.0 = fully transparent, 1.0 = fully opaque
_MINI_BRIGHTNESS_BOOST = 1.6


class Dsp3270Device(DeviceBase):
    """
    IBM 3270 Model 2 display terminal device plugin.
    Handles devclass="DSP" devices reported by Hercules.
    """

    device_classes = ["DSP"]
    bitmap_name    = "3270.png"

    def __init__(self, context: Optional[DeviceContext] = None):
        super().__init__(context)

        self._workspace  = None   # TerminalScreen — created once, reused
        self._scroll     = None   # QScrollArea wrapping _workspace — created once, reused
        self._ws_container = None # QWidget with 4px margins wrapping _scroll — created once, reused
        self._mini_lines: list[str] = []
        self._mini_cells: list = []
        self._session: Optional[Tn3270Session] = None
        self._import_error: str = ""
        self._host = self.host or "127.0.0.1"
        self._font_family = terminal_font_family()
        self._font_size_px = self._load_font_size()
        self._btn_connect = None
        self._btn_disconnect = None
        self._disconnect_dlg = None

        self._mini_screen = MiniScreenOverlay(
            _MINI_X, _MINI_Y, _MINI_W, _MINI_H,
            max_lines=ROWS + 1, max_cols=COLS,
            font_family=self._font_family,
            bold=True,
            opacity=_MINI_OPACITY,
            brightness_boost=_MINI_BRIGHTNESS_BOOST,
        )

        # Start the TN3270 session if we have API access
        if self.api_client is not None:
            try:
                port = self.api_client.get_console_port(default=3270)
                self._session = Tn3270Session()
                self._session.screen_updated.connect(
                    self._on_screen_updated, Qt.QueuedConnection
                )
                self._session.start(self._host, port, self.devnum)
            except Exception as exc:
                logger.error("Failed to start TN3270 session: %s", exc)
                self._import_error = str(exc)

    def _session_connected(self) -> bool:
        return bool(self._session is not None and self._session.is_connected)

    def _set_socket_button(self, button, enabled: bool):
        if button is not None and shiboken6.isValid(button):
            button.setEnabled(enabled)
            return button
        return None

    def _focus_workspace(self) -> None:
        if self._workspace is not None:
            self._workspace.setFocus()

    def _enqueue_session_action(self, action: str, data: bytes = b"") -> None:
        if self._session is not None:
            self._session.enqueue_action(action, data)
        self._focus_workspace()

    def _build_setup_dialog(self, parent: QWidget | None) -> tuple[QDialog, QSpinBox]:
        dlg = QDialog(parent)
        dlg.setWindowTitle("3270 Setup")
        layout = QVBoxLayout(dlg)
        form = QFormLayout()

        font_size = QSpinBox(dlg)
        font_size.setRange(10, 32)
        font_size.setValue(self._font_size_px)
        form.addRow("Font size:", font_size)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        return dlg, font_size

    # ── DeviceBase interface ───────────────────────────────────────────────

    def create_workspace(self, parent: QWidget) -> QWidget:
        if self._import_error:
            widget = QWidget(parent)
            layout = QVBoxLayout(widget)
            msg = QLabel(
                f"TN3270 not available:\n{self._import_error}\n\n"
                "Device: 3270 terminal",
                widget
            )
            msg.setStyleSheet("color: #FF6666; font-size: 12px;")
            layout.addWidget(msg)
            return widget

        if self._workspace is None:
            from ..widgets.terminal_screen import TerminalScreen
            self._workspace = TerminalScreen(font_size_px=self._font_size_px)
            # Route key events to the session
            self._workspace.key_action.connect(self._route_key)
            # Connect session updates to workspace (queued — session runs in bg thread)
            if self._session is not None:
                self._session.screen_updated.connect(
                    self._workspace.update_screen, Qt.QueuedConnection
                )
                self._session.connected_changed.connect(
                    self._workspace.set_connected, Qt.QueuedConnection
                )
                self._session.connected_changed.connect(
                    self._on_connection_state_changed, Qt.QueuedConnection
                )
                # Sync current state immediately so the widget doesn't start blank/disconnected
                self._workspace.set_connected(self._session.is_connected)
                self._on_connection_state_changed(self._session.is_connected)
                self._session.emit_current_screen()

            # Wrap once in a scroll area — kept alive as self._scroll so the
            # QScrollArea (and its owned TerminalScreen child) are never GC'd.
            self._scroll = QScrollArea()
            self._scroll.setWidget(self._workspace)
            self._scroll.setWidgetResizable(False)
            self._scroll.setAlignment(Qt.AlignCenter)
            self._scroll.setFrameShape(QFrame.NoFrame)
            self._scroll.setStyleSheet(f"QScrollArea {{ border: {WORKSPACE_FRAME}; }}")

            # Container with 4px margins so the visible gap around the frame
            # matches the 8px seen on Console and printer workspaces.
            self._ws_container = QWidget()
            _cl = QVBoxLayout(self._ws_container)
            _cl.setContentsMargins(4, 4, 4, 4)
            _cl.setSpacing(0)
            _cl.addWidget(self._scroll)

        return self._ws_container

    def get_buttons(self) -> list[ButtonDef]:
        """Return two-per-row 3270 AID key buttons."""

        def _aid(byte_val: int):
            return lambda: self._send_aid(byte_val)

        def _action(act: str, data: bytes = b''):
            return lambda: self._send_action(act, data)

        return [
            # Row 1
            ButtonDef("PA1",    _aid(0x6c), tooltip="Program Access 1"),
            ButtonDef("PA2",    _aid(0x6e), tooltip="Program Access 2"),
            # Row 2
            ButtonDef("PA3",    _aid(0x6b), tooltip="Program Access 3"),
            ButtonDef("Clear",  _aid(0x6d), tooltip="Clear screen"),
            # Row 3
            ButtonDef("SysReq", _action('sysreq_attn'), tooltip="System Request (IAC IP)"),
            ButtonDef("Attn",   _action('sysreq_attn'), tooltip="Attention (IAC IP)"),
            # Row 4
            ButtonDef("Reset",  _action('reset'),        tooltip="Reset keyboard lock"),
            ButtonDef("ErInp",  _action('erase_input'),  tooltip="Erase all input fields"),
            # Row 5
            ButtonDef("Dup",    _action('dup'),           tooltip="Duplicate field"),
            ButtonDef("FldMrk", _action('field_mark'),   tooltip="Field Mark"),
            # Row 6
            ButtonDef("Setup", self._do_setup, full_width=True),
            ButtonDef("Socket", is_label=True),
            ButtonDef("Connect", self._do_connect,
                      on_created=self._on_connect_button_created,
                      full_width=True),
            ButtonDef("Disconnect", self._do_disconnect,
                      on_created=self._on_disconnect_button_created,
                      full_width=True),
        ]

    def button_column_width(self) -> int:
        return 160

    def button_columns(self) -> int:
        return 2

    def draw_room_overlay(self, painter: QPainter, rect) -> None:
        if self._mini_cells:
            self._mini_screen.render_cells(
                painter,
                rect,
                self._mini_cells,
                rows=ROWS + 1,
                cols=COLS,
            )
        else:
            self._mini_screen.render(painter, rect, self._mini_lines)

    def cleanup(self) -> None:
        if self._session is not None:
            self._session.stop()
            self._session.join(timeout=1.0)

    def on_selected(self, api_client=None) -> None:
        if self._workspace is not None:
            self._workspace.setFocus()

    # ── Internal helpers ───────────────────────────────────────────────────

    @Slot(list, int, bool, bool)
    def _on_screen_updated(self, cells: list, cursor: int,
                           locked: bool, insert: bool) -> None:
        """Build the mini-screen text lines whenever the screen is updated."""
        # Build OIA status row as cells and append to the 24-row screen cells
        parts = []
        if locked:
            parts.append("X SYSTEM")
        if insert:
            parts.append("INSERT")
        r, c = divmod(cursor, COLS)
        status = ("  ".join(parts)).ljust(COLS - 5) + f"{r+1:02d}/{c+1:02d}"
        oia_cells = [(ch, _FG_DEF, _OIA_BG, False) for ch in status[:COLS].ljust(COLS)]
        self._mini_cells = list(cells) + oia_cells
        if self._session is not None:
            self._mini_lines = self._session._screen.build_text_lines(
                locked=locked, insert=insert, cursor=cursor
            )

    @Slot(str, bytes)
    def _route_key(self, action: str, data: bytes) -> None:
        if self._session is not None:
            self._session.enqueue_action(action, data)

    @Slot(bool)
    def _on_connection_state_changed(self, connected: bool) -> None:
        self._btn_connect = self._set_socket_button(self._btn_connect, not connected)
        self._btn_disconnect = self._set_socket_button(self._btn_disconnect, connected)

    def _on_connect_button_created(self, button) -> None:
        self._btn_connect = button
        self._on_connection_state_changed(self._session_connected())

    def _on_disconnect_button_created(self, button) -> None:
        self._btn_disconnect = button
        self._on_connection_state_changed(self._session_connected())

    def _send_aid(self, aid_byte: int) -> None:
        self._enqueue_session_action("aid", bytes([aid_byte]))

    def _send_action(self, action: str, data: bytes = b'') -> None:
        self._enqueue_session_action(action, data)

    def _load_font_size(self) -> int:
        if self.config is None:
            return DSP3270_FONT_SIZE_PX
        raw = self.config.get_setting("devices", f"dsp3270_font_size_{self.devnum}", str(DSP3270_FONT_SIZE_PX))
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return DSP3270_FONT_SIZE_PX
        return max(10, min(32, value))

    def _do_setup(self) -> None:
        parent = self._ws_container or self._workspace
        dlg, font_size = self._build_setup_dialog(parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_size = font_size.value()
        if new_size == self._font_size_px:
            return

        self._font_size_px = new_size
        if self.config is not None:
            self.config.set_setting("devices", f"dsp3270_font_size_{self.devnum}", str(new_size))
        if self._workspace is not None:
            self._workspace.set_font_size(new_size)
        if self._scroll is not None:
            self._scroll.setWidgetResizable(False)

    def _do_connect(self) -> None:
        if self._session is not None:
            self._session.connect_session()
            self._on_connection_state_changed(self._session_connected())

    def _do_disconnect(self) -> None:
        parent = self._ws_container or self._workspace
        dlg = QMessageBox(
            QMessageBox.Icon.Question,
            "Disconnect 3270",
            "Disconnect the 3270 socket connection?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            parent,
        )
        dlg.setDefaultButton(QMessageBox.StandardButton.No)
        dlg.accepted.connect(self._on_disconnect_accepted)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        self._disconnect_dlg = dlg
        dlg.open()

    def _on_disconnect_accepted(self) -> None:
        self._disconnect_dlg = None
        if self._session is not None:
            self._session.disconnect_session()
            self._on_connection_state_changed(False)
