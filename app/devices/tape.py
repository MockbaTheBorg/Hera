# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Hera tape device plugin.

Handles devclass="TAPE" (IBM 2401/3480/3490/3590 tape drives).

Room rendering:
  - Base bitmap: 2401.png (135×269px)
  - When a tape is loaded, overlay the reel bitmap at (10, 31, 115, 155):
      2401prot.png  — write-protected (ro or *FP* in assignment)
      2401unpr.png  — read-write
  - Drive Display string drawn right-aligned in text area (75, 111, 45, 12),
    dark gray, 9px font — drawn even when no tape is loaded.

Geometry (from Jason t_devimg entry):
  { DEV_TAPE, 2401, "T2401", "TPROT", "TUNPR", 10, 31, 115, 155, 39, 7, 75, 111, 45, 12 }

Button column (via create_button_widget):
  Mount   — enabled when no tape loaded
  Unmount — enabled when tape loaded
  New     — always enabled

Mount:   devinit <devnum> <folder>/<file> [ro]
Unmount: devinit <devnum> *
New:     sh hetinit -d <folder>/<file> <VOLSER> [<OWNER>]  then auto-mount RW

tapes_folder config (connection.tapes_folder, default "tapes"):
  Path relative to Hercules working directory. Must not start with '.' or '/'.
"""

import logging
import os
from typing import Optional

import shiboken6
from PySide6.QtCore import Qt, QRect, QObject, Signal, Slot, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QMessageBox,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..device_base import (
    DeviceBase,
    ButtonDef,
    DeviceContext,
)
from ..theme import BUTTON_HEIGHT, button_style
from .media_common import (
    create_command_output_workspace,
    label_from_path,
    render_workspace_commands,
    run_command_output,
)
from .tape_support import (
    MountDialog,
    NewTapeDialog,
    TapeDisplayState,
    parse_assignment,
    strip_herc_prefix,
    validate_folder,
)

logger = logging.getLogger(__name__)

from ..device_base import bitmaps_dir as _bitmaps_dir

# Geometry (bitmap-relative, from Jason t_devimg)
_REEL_RECT  = QRect(10, 31, 115, 155)
_TEXT_LEFT  = 75
_TEXT_TOP   = 111
_TEXT_W     = 45
_TEXT_H     = 12
_TEXT_COLOR = QColor(64, 64, 64)
_DISPLAY_TICK_MS = 500

# Commands sent to Hercules when the device is selected.
# Each template is formatted with .format(**kwargs) before being sent.
# Available substitution variable:
#   {devnum}  — Hercules device address (e.g. "0A80")
# No other variables are supported; using an unknown variable raises KeyError.
WORKSPACE_COMMANDS = [
    "devlist {devnum}",
]

class _TapeSignals(QObject):
    button_state_changed = Signal(bool)
    display_state_changed = Signal()


# ── Device plugin ─────────────────────────────────────────────────────────────

class TapeDevice(DeviceBase):
    """IBM 2401/3480/3490/3590 tape drive device."""

    device_classes: list[str] = ["TAPE"]
    bitmap_name: str = "2401.png"
    room_light_origin = (39, 7)

    def __init__(self, context: Optional[DeviceContext] = None):
        super().__init__(context)
        self._api = self.api_client
        self._config = self.config
        self._loaded: bool = False
        self._protected: bool = False
        self._display_primary: str = ""
        self._display_secondary: Optional[str] = None
        self._display_mode: str = "static"
        self._display_phase: bool = False
        self._vol_label: str = ""
        self._last_assignment: Optional[str] = None
        self._prot_pixmap: Optional[QPixmap] = self._load_pixmap("2401prot.png")
        self._unpr_pixmap: Optional[QPixmap] = self._load_pixmap("2401unpr.png")
        self._workspace: Optional[QWidget] = None
        self._output: Optional[QPlainTextEdit] = None
        self._btn_mount: Optional[QPushButton] = None
        self._btn_unmount: Optional[QPushButton] = None
        self._signals = _TapeSignals()
        self._display_timer = QTimer(self._signals)
        self._display_timer.setInterval(_DISPLAY_TICK_MS)
        self._display_timer.timeout.connect(self._on_display_tick)
        self._signals.button_state_changed.connect(
            self._apply_button_states, Qt.QueuedConnection
        )
        self._signals.display_state_changed.connect(
            self._sync_display_animation, Qt.QueuedConnection
        )

    def _load_pixmap(self, filename: str) -> Optional[QPixmap]:
        path = os.path.join(_bitmaps_dir(), filename)
        if not os.path.exists(path):
            logger.warning("TAPE: bitmap not found: %s", path)
            return None
        px = QPixmap(path)
        return None if px.isNull() else px

    def on_bitmap_theme_changed(self) -> None:
        self._prot_pixmap = self._load_pixmap("2401prot.png")
        self._unpr_pixmap = self._load_pixmap("2401unpr.png")
        self.request_room_repaint()

    def _parent_widget(self) -> Optional[QWidget]:
        return self._output.window() if self._output else None

    def _set_button_enabled(self, button: Optional[QPushButton], enabled: bool) -> Optional[QPushButton]:
        if button is not None and shiboken6.isValid(button):
            button.setEnabled(enabled)
            return button
        return None

    def _make_button(self, label: str, callback, *, enabled: bool = True) -> QPushButton:
        button = QPushButton(label)
        button.setFixedHeight(BUTTON_HEIGHT)
        button.setStyleSheet(button_style())
        button.setEnabled(enabled)
        button.clicked.connect(callback)
        return button

    def _warning(self, title: str, message: str) -> None:
        QMessageBox.warning(self._parent_widget(), title, message)

    def _confirm(self, title: str, message: str) -> bool:
        reply = QMessageBox.question(
            self._parent_widget(),
            title,
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _invalidate_assignment_cache(self) -> None:
        self._last_assignment = None

    def _run_and_refresh(self, client, cmd: str, *, loaded: Optional[bool] = None) -> None:
        self._run_cmd(client, cmd)
        self._invalidate_assignment_cache()
        if loaded is not None:
            self._loaded = loaded
            if not loaded:
                self._protected = False
                self._set_display_state(TapeDisplayState())
                self._vol_label = ""
                self._signals.display_state_changed.emit()
            self._apply_button_states(loaded)
        self._refresh_output(client)

    def _set_display_state(self, display_state: TapeDisplayState) -> None:
        self._display_primary = display_state.primary_text
        self._display_secondary = display_state.secondary_text
        self._display_mode = display_state.mode
        self._display_phase = False

    def _is_display_animated(self) -> bool:
        return self._display_mode in {"blinking", "alternating"} and bool(self._display_primary)

    def _visible_display_text(self) -> str:
        if not self._display_primary:
            return ""
        if self._display_mode == "blinking":
            return "" if self._display_phase else self._display_primary
        if self._display_mode == "alternating" and self._display_secondary:
            return self._display_secondary if self._display_phase else self._display_primary
        return self._display_primary

    @Slot()
    def _sync_display_animation(self) -> None:
        if self._is_display_animated():
            if not self._display_timer.isActive():
                self._display_timer.start()
        elif self._display_timer.isActive():
            self._display_timer.stop()
        self.request_room_repaint()

    @Slot()
    def _on_display_tick(self) -> None:
        self._display_phase = not self._display_phase
        self.request_room_repaint()

    @property
    def _tapes_folder(self) -> str:
        if self._config and hasattr(self._config, "tapes_folder"):
            return validate_folder(self._config.tapes_folder)
        return "tapes"

    # ── Polling ───────────────────────────────────────────────────────────────

    def poll(self, api_client) -> None:
        dev = self.room_device_info()
        if dev is None:
            return
        assignment = dev.get("assignment", "").strip()
        if assignment == self._last_assignment:
            return
        self._last_assignment = assignment
        self.mark_room_activity()
        file_path, is_protected, display_state = parse_assignment(assignment)
        self._loaded = file_path is not None
        self._protected = is_protected
        self._set_display_state(display_state)
        self._vol_label = label_from_path(file_path) if file_path else ""
        self._signals.button_state_changed.emit(self._loaded)
        self._signals.display_state_changed.emit()

    @Slot(bool)
    def _apply_button_states(self, loaded: bool) -> None:
        self._btn_mount = self._set_button_enabled(self._btn_mount, not loaded)
        self._btn_unmount = self._set_button_enabled(self._btn_unmount, loaded)

    # ── Button column ─────────────────────────────────────────────────────────

    def create_button_widget(self, button_column) -> QWidget:
        """Return a widget with Mount / Unmount / New buttons for the column."""
        self._btn_mount = None
        self._btn_unmount = None
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._btn_mount = self._make_button("Mount", self._on_mount_clicked, enabled=not self._loaded)
        layout.addWidget(self._btn_mount)

        self._btn_unmount = self._make_button("Unmount", self._on_unmount_clicked, enabled=self._loaded)
        layout.addWidget(self._btn_unmount)

        layout.addWidget(self._make_button("New", self._on_new_clicked))

        return widget

    def get_buttons(self) -> list[ButtonDef]:
        return []   # buttons supplied via create_button_widget

    def has_button_column_content(self) -> bool:
        return True

    # ── Workspace ─────────────────────────────────────────────────────────────

    def create_workspace(self, parent: QWidget) -> QWidget:
        if self._workspace is None:
            self._workspace, self._output = create_command_output_workspace(parent)
        return self._workspace

    def on_selected(self, api_client=None) -> None:
        if self._output is None:
            return
        client = api_client or self._api
        if client is None:
            return
        self._refresh_output(client)

    def _refresh_output(self, client):
        if self._output is None:
            return
        render_workspace_commands(self._output, client, WORKSPACE_COMMANDS, devnum=self.devnum)

    def _get_tape_list(self, client) -> list:
        """List files in the tapes folder via Hercules 'sh ls <folder>'."""
        cmd = f"sh ls {self._tapes_folder}"
        lines = run_command_output(client, cmd)
        if not lines:
            return []
        files = []
        for line in lines:
            stripped = strip_herc_prefix(line)
            if not stripped or "sh ls" in stripped or stripped.startswith("sh:"):
                continue
            files.append(stripped)
        return files

    def _run_cmd(self, client, cmd: str):
        return run_command_output(client, cmd) or []

    def _find_mounts(self, client, tape_path: str) -> list:
        """
        Return a list of (devnum, is_protected) for every TAPE unit other than
        self that currently has *tape_path* mounted.
        """
        result = client.get_devices()
        if not result:
            return []
        mounts = []
        for dev in result.get("devices", []):
            if dev.get("devclass", "") != "TAPE":
                continue
            if dev.get("devnum", "") == self.devnum:
                continue
            file_path, is_protected, _ = parse_assignment(dev.get("assignment", ""))
            if file_path == tape_path:
                mounts.append((dev["devnum"], is_protected))
        return mounts

    def _file_exists(self, client, tape_path: str) -> bool:
        """Return True if *tape_path* exists on the Hercules host."""
        filename = os.path.basename(tape_path)
        cmd = f"sh ls {tape_path}"
        lines = run_command_output(client, cmd)
        if not lines:
            return False
        for line in lines:
            stripped = strip_herc_prefix(line)
            if not stripped or stripped == cmd or stripped.startswith("sh:"):
                continue
            if stripped == filename or stripped.endswith("/" + filename):
                return True
        return False

    # ── Button callbacks ──────────────────────────────────────────────────────

    def _on_mount_clicked(self):
        client = self._api
        if client is None:
            return

        files = self._get_tape_list(client)
        if not files:
            self._warning("Mount Tape", f"No files found in folder '{self._tapes_folder}'.")
            return

        dlg = MountDialog(files, self._parent_widget())
        if dlg.exec() != QDialog.Accepted:
            return

        tape_path = f"{self._tapes_folder}/{dlg.selected_file()}"
        mounts = self._find_mounts(client, tape_path)

        if dlg.is_readonly():
            # RO mount: deny if any other unit has it mounted RW
            rw_units = [devnum for devnum, prot in mounts if not prot]
            if rw_units:
                self._warning(
                    "Mount Tape",
                    f"'{dlg.selected_file()}' is already mounted read-write "
                    f"on unit {rw_units[0]}.\n"
                    "Unmount it there first before mounting read-only here.",
                )
                return
        else:
            # RW mount: deny if mounted anywhere else (RO or RW)
            if mounts:
                units = ", ".join(devnum for devnum, _ in mounts)
                self._warning(
                    "Mount Tape",
                    f"'{dlg.selected_file()}' is already mounted on unit {units}.\n"
                    "Unmount it there first before mounting read-write here.",
                )
                return

        cmd = f"devinit {self.devnum} {tape_path}"
        if dlg.is_readonly():
            cmd += " ro"
        self._run_and_refresh(client, cmd)

    def _on_unmount_clicked(self):
        client = self._api
        if client is None:
            return
        self._run_and_refresh(client, f"devinit {self.devnum} *", loaded=False)

    def _on_new_clicked(self):
        client = self._api
        if client is None:
            return

        if self._loaded and not self._confirm(
            "New Tape",
                f"A tape is currently mounted on device {self.devnum}.\n"
                "Replace with the new tape?",
        ):
            return

        dlg = NewTapeDialog(self._parent_widget())
        if dlg.exec() != QDialog.Accepted:
            return

        tape_path = f"{self._tapes_folder}/{dlg.filename()}"

        if self._file_exists(client, tape_path):
            mounts = self._find_mounts(client, tape_path)
            if mounts:
                units = ", ".join(devnum for devnum, _ in mounts)
                self._warning(
                    "New Tape",
                    f"'{dlg.filename()}' is currently mounted on unit {units}.\n"
                    "Unmount it there first before overwriting.",
                )
                return
            if not self._confirm(
                "New Tape",
                f"'{dlg.filename()}' already exists. Overwrite it?",
            ):
                return

        hetinit_cmd = f"sh hetinit -d {tape_path} {dlg.volser()}"
        if dlg.owner():
            hetinit_cmd += f" {dlg.owner()}"
        self._run_cmd(client, hetinit_cmd)
        self._run_and_refresh(client, f"devinit {self.devnum} {tape_path}", loaded=True)

    # ── Room overlay ──────────────────────────────────────────────────────────

    def draw_room_overlay(self, painter: QPainter, rect: QRect) -> None:
        # Reel — only when loaded
        if self._loaded:
            pixmap = self._prot_pixmap if self._protected else self._unpr_pixmap
            if pixmap is not None:
                painter.drawPixmap(
                    QRect(rect.left() + _REEL_RECT.left(),
                          rect.top()  + _REEL_RECT.top(),
                          _REEL_RECT.width(), _REEL_RECT.height()),
                    pixmap,
                )

        # Drive display text — always when non-empty
        display_text = self._visible_display_text()
        if display_text:
            font = QFont()
            font.setPixelSize(9)
            painter.save()
            painter.setFont(font)
            painter.setPen(_TEXT_COLOR)
            painter.drawText(
                QRect(rect.left() + _TEXT_LEFT, rect.top() + _TEXT_TOP,
                      _TEXT_W, _TEXT_H),
                Qt.AlignRight | Qt.AlignVCenter,
                display_text,
            )
            painter.restore()

    def room_light_on_colors(self) -> Optional[list[QColor]]:
        mode_color = QColor(255, 96, 96) if self._protected else QColor(96, 255, 96)
        return [
            QColor(255, 176, 176),
            QColor(176, 255, 176),
            QColor(176, 255, 176),
            QColor(224, 224, 144),
            mode_color,
        ]

    def room_light_levels(self) -> Optional[list[float]]:
        protected = self.room_state_light(self._protected)
        loaded = self.room_state_light(self._loaded)
        return [self.room_connected_light(), self.room_activity_level(), protected, loaded, loaded]
