# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Hera IBM 3270 display terminal device plugin.

Handles devclass="DSP" — IBM 3270 terminals. Monitor model (screen size) is a
per-device, persisted setting exposed in the Setup dialog; default is Model 2
(80×24), matching Hera's original fixed behavior.

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
    QComboBox,
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
from ..widgets.terminal_screen import _FG_DEF, _OIA_BG, _AID_ENTER
from ..widgets.terminal_style import DSP3270_FONT_SIZE_PX, terminal_font_family
from .dsp3270_protocol import MODEL_DIMENSIONS, DEFAULT_MODEL
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
    IBM 3270 display terminal device plugin. Monitor model is per-device and
    configurable via Setup (default Model 2, 80×24).
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
        self._cursor_row: int = 0
        self._cursor_col: int = 0
        self._protected_mask: list[bool] = []
        self._session: Optional[Tn3270Session] = None
        self._import_error: str = ""
        self._host = self.host or "127.0.0.1"
        self._font_family = terminal_font_family()
        self._font_size_px = self._load_font_size()
        self._model = self._load_model()
        self._rows, self._cols = MODEL_DIMENSIONS[self._model]
        self._btn_connect = None
        self._btn_disconnect = None
        self._disconnect_dlg = None
        self._port: int = 3270

        self._mini_screen = MiniScreenOverlay(
            _MINI_X, _MINI_Y, _MINI_W, _MINI_H,
            max_lines=self._rows + 1, max_cols=self._cols,
            font_family=self._font_family,
            bold=True,
            opacity=_MINI_OPACITY,
            brightness_boost=_MINI_BRIGHTNESS_BOOST,
        )

        # Start the TN3270 session if we have API access
        if self.api_client is not None:
            try:
                self._port = self.api_client.get_console_port(default=3270)
                self._session = Tn3270Session(model=self._model)
                self._wire_session(self._session)
                self._session.start(self._host, self._port, self.devnum)
            except Exception as exc:
                logger.error("Failed to start TN3270 session: %s", exc)
                self._import_error = str(exc)

    def _wire_session(self, session: Tn3270Session) -> None:
        """Signal wiring that must hold regardless of GUI selection (drives
        the room mini-screen overlay). Reused by __init__ and set_model()."""
        session.screen_updated.connect(self._on_screen_updated, Qt.QueuedConnection)

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

    def _enqueue_session_action(self, action: str, data: bytes = b"", *, focus: bool = True) -> None:
        if self._session is not None:
            self._session.enqueue_action(action, data)
        if focus:
            self._focus_workspace()

    def type_text(self, text: str) -> None:
        """Type text into the terminal without needing the workspace to exist
        or the device to be selected. Encodes each character (cp037) and
        sends an AID Enter only on '\\n' — same behavior as pasting text via
        Ctrl+V (TerminalScreen._emit_clipboard_text), but delivered straight
        to the session so it works headlessly. A trailing newline is not
        required: text with none simply sits pending, exactly as if a human
        had typed it and not yet pressed Enter."""
        batch = bytearray()
        for ch in text:
            if ch == "\n":
                if batch:
                    self._enqueue_session_action("input", bytes(batch), focus=False)
                    batch.clear()
                self._enqueue_session_action("aid", bytes([_AID_ENTER]), focus=False)
                continue
            if ch.isprintable():
                try:
                    batch.extend(ch.encode("cp037"))
                except (UnicodeEncodeError, LookupError):
                    pass
        if batch:
            self._enqueue_session_action("input", bytes(batch), focus=False)

    def _build_setup_dialog(self, parent: QWidget | None) -> tuple[QDialog, QSpinBox, QComboBox]:
        dlg = QDialog(parent)
        dlg.setWindowTitle("3270 Setup")
        layout = QVBoxLayout(dlg)
        form = QFormLayout()

        font_size = QSpinBox(dlg)
        font_size.setRange(10, 32)
        font_size.setValue(self._font_size_px)
        form.addRow("Font size:", font_size)

        model_combo = QComboBox(dlg)
        for model, (rows, cols) in sorted(MODEL_DIMENSIONS.items()):
            model_combo.addItem(f"Model {model} ({cols}×{rows})", model)
        idx = model_combo.findData(self._model)
        model_combo.setCurrentIndex(max(idx, 0))
        form.addRow("Monitor model:", model_combo)
        layout.addLayout(form)

        hint = QLabel(
            "Model changes take effect after reconnecting (Connect/Disconnect)\n"
            "or after deselecting and reselecting this terminal.",
            dlg,
        )
        hint.setStyleSheet("color: #999999; font-size: 10px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        return dlg, font_size, model_combo

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
            self._workspace = TerminalScreen(
                font_size_px=self._font_size_px, rows=self._rows, cols=self._cols
            )
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
                rows=self._rows + 1,
                cols=self._cols,
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
        r, c = divmod(cursor, self._cols)
        status = ("  ".join(parts)).ljust(self._cols - 5) + f"{r+1:02d}/{c+1:02d}"
        oia_cells = [(ch, _FG_DEF, _OIA_BG, False) for ch in status[:self._cols].ljust(self._cols)]
        self._mini_cells = list(cells) + oia_cells
        self._cursor_row, self._cursor_col = r, c
        if self._session is not None:
            self._mini_lines = self._session._screen.build_text_lines(
                locked=locked, insert=insert, cursor=cursor
            )
            self._protected_mask = self._session._screen.protected_mask()

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

    def _send_aid(self, aid_byte: int, *, focus: bool = True) -> None:
        self._enqueue_session_action("aid", bytes([aid_byte]), focus=focus)

    def _send_action(self, action: str, data: bytes = b'', *, focus: bool = True) -> None:
        self._enqueue_session_action(action, data, focus=focus)

    def _load_font_size(self) -> int:
        if self.config is None:
            return DSP3270_FONT_SIZE_PX
        raw = self.config.get_setting("devices", f"dsp3270_font_size_{self.devnum}", str(DSP3270_FONT_SIZE_PX))
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return DSP3270_FONT_SIZE_PX
        return max(10, min(32, value))

    def set_font_size(self, new_size: int) -> None:
        """Non-interactive core of the Setup dialog's font-size change. Used
        by both the dialog and the scripting API."""
        new_size = max(10, min(32, int(new_size)))
        if new_size == self._font_size_px:
            return
        self._font_size_px = new_size
        if self.config is not None:
            self.config.set_setting("devices", f"dsp3270_font_size_{self.devnum}", str(new_size))
        if self._workspace is not None:
            self._workspace.set_font_size(new_size)
        if self._scroll is not None:
            self._scroll.setWidgetResizable(False)

    def _load_model(self) -> int:
        if self.config is None:
            return DEFAULT_MODEL
        raw = self.config.get_setting("devices", f"dsp3270_model_{self.devnum}", str(DEFAULT_MODEL))
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_MODEL
        return value if value in MODEL_DIMENSIONS else DEFAULT_MODEL

    def set_model(self, model: int) -> None:
        """Non-interactive core of the Setup dialog's monitor-model change.
        Used by both the dialog and the scripting API. Rebuilds the live
        session against the new geometry immediately; the visible workspace
        widget (if any) is discarded so it's rebuilt fresh, correctly sized,
        the next time this device is selected."""
        model = int(model)
        if model not in MODEL_DIMENSIONS:
            raise ValueError(f"Unknown monitor model {model}")
        if model == self._model:
            return
        self._model = model
        self._rows, self._cols = MODEL_DIMENSIONS[model]
        if self.config is not None:
            self.config.set_setting("devices", f"dsp3270_model_{self.devnum}", str(model))

        old_session = self._session
        self._session = None
        if old_session is not None:
            old_session.stop()
            old_session.join(timeout=1.0)
        if self.api_client is not None:
            self._session = Tn3270Session(model=self._model)
            self._wire_session(self._session)
            self._session.start(self._host, self._port, self.devnum)
        self._on_connection_state_changed(self._session_connected())

        # Explicit deleteLater() (not just dropping the references) is required
        # here: set_model() can run via the scripting API with the device never
        # selected in the GUI, so device_area.py may hold no reference to this
        # container at all. Left as a bare reference drop, the old TerminalScreen
        # survives via its own internal cycle (self._blink.timeout is connected
        # to self._on_blink, a bound method that references the widget back) --
        # simple refcounting can't free a cycle, so it becomes orphaned cyclic
        # garbage. Whenever Python's GC eventually collects it, the underlying
        # QTimer gets destroyed on whatever thread is running the GC pass at
        # that moment (e.g. the poller worker thread or a session's socket
        # thread), which crashes with "Timers cannot be stopped from another
        # thread". Calling deleteLater() here forces deterministic, GUI-thread
        # destruction instead. Safe to call even if device_area.py also holds
        # (and later deleteLater()s) the same object -- Qt handles that fine.
        if self._ws_container is not None:
            self._ws_container.deleteLater()

        self._workspace = None
        self._scroll = None
        self._ws_container = None

    def _do_setup(self) -> None:
        parent = self._ws_container or self._workspace
        dlg, font_size, model_combo = self._build_setup_dialog(parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.set_font_size(font_size.value())
        self.set_model(model_combo.currentData())

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
