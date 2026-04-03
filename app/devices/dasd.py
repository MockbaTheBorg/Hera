# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Hera DASD device plugin.

Handles devclass="DASD" (IBM 2311 disk storage).

Room rendering:
  - Base bitmap: 2311.png (129×251px)
  - When a volume is mounted, overlay 2311disc.png (129×87px) at the top of
    the bitmap, then print the volume label right-aligned in the label area.

Overlay geometry (from Jason t_devimg entry):
  { DEV_DASD, 2311, "D2311", "DISC1", "DISC1", 0, 0, 129, 87, 21, 74, 43, 22, 43, 11 }
  listrc = (0, 0, 129, 87)   — disc bitmap at top of device bitmap
  textrc = (43, 22, 86, 33)  — label text area (right-aligned)

Mount detection:
  The Hercules API assignment field contains the device file path when a volume
  is mounted, optionally prefixed by a status token like *64*:
    "*64* z24min/sares1.cckd [cu 3990-6] [10017 cyls] [1 sfs] IO[142323]"

Volume label:
  The Hercules API does not expose the VOLSER.  The filename without extension
  is used as the label (e.g. "z24min/sares1.cckd" → "SARES1").

Workspace:
  When the device is selected, WORKSPACE_COMMANDS are sent to Hercules via the
  syslog API and their output is shown in a read-only text area (black on white).
  Add or remove entries from WORKSPACE_COMMANDS to customise what is shown.
"""

import logging
import os
import re
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from ..device_base import DeviceBase, ButtonDef, DeviceContext
from .media_common import (
    create_command_output_workspace,
    label_from_path,
    render_workspace_commands,
)

logger = logging.getLogger(__name__)

from ..device_base import bitmaps_dir as _bitmaps_dir

# Geometry (bitmap-relative coordinates, from Jason t_devimg)
_DISC_RECT   = QRect(0, 0, 129, 87)
_TEXT_X0     = 43
_TEXT_Y0     = 22
_TEXT_RIGHT  = 86
_TEXT_BOTTOM = 33
_TEXT_COLOR  = QColor(64, 64, 64)    # matches Jason's RGB(64,64,64)

# Commands sent to Hercules when the device is selected.
# Each template is formatted with .format(**kwargs) before being sent.
# Available substitution variable:
#   {devnum}  — Hercules device address (e.g. "0A80")
# No other variables are supported; using an unknown variable raises KeyError.
WORKSPACE_COMMANDS = [
    "sfd {devnum}",
]

def _parse_assignment(assignment: str) -> Optional[str]:
    """
    Return the DASD file path from a Hercules assignment field, or None if
    no file path is present (device not mounted).

    Handles the *NNN* status prefix Hercules prepends when the device is active:
      "*64* z24min/sares1.cckd [cu 3990-6] [10017 cyls] [1 sfs] IO[44054] open"
    """
    for tok in assignment.split():
        if re.fullmatch(r'\*\d+\*', tok):
            continue            # status flag e.g. *64* — skip
        if tok.startswith("["):
            continue            # info bracket — skip
        if tok.startswith("sf="):
            continue            # shadow file spec — skip
        if tok in ("open", "closed"):
            continue            # state keyword — skip
        return tok              # first plain token is the file path
    return None

class DasdDevice(DeviceBase):
    """IBM 2311 disk storage device."""

    device_classes: list[str] = ["DASD"]
    bitmap_name: str = "2311.png"
    room_light_origin = (21, 74)

    def __init__(self, context: Optional[DeviceContext] = None):
        super().__init__(context)
        self._api = self.api_client
        self._mounted: bool = False
        self._vol_label: str = ""
        self._last_assignment: Optional[str] = None
        self._disc_pixmap: Optional[QPixmap] = self._load_disc_pixmap()
        self._workspace: Optional[QWidget] = None
        self._output: Optional[QPlainTextEdit] = None

    def _load_disc_pixmap(self) -> Optional[QPixmap]:
        path = os.path.join(_bitmaps_dir(), "2311disc.png")
        if not os.path.exists(path):
            logger.warning("DASD: disc overlay bitmap not found: %s", path)
            return None
        px = QPixmap(path)
        if px.isNull():
            logger.warning("DASD: failed to load disc overlay bitmap: %s", path)
            return None
        return px

    def on_bitmap_theme_changed(self) -> None:
        self._disc_pixmap = self._load_disc_pixmap()
        self.request_room_repaint()

    # ── Polling ──────────────────────────────────────────────────────────────

    def poll(self, api_client) -> None:
        """Refresh mount state from the Hercules API."""
        dev = self.room_device_info()
        if dev is None:
            return
        assignment = dev.get("assignment", "").strip()
        if assignment == self._last_assignment:
            return
        self._last_assignment = assignment
        self.mark_room_activity()

        dasd_file = _parse_assignment(assignment)
        mounted = dasd_file is not None
        vol_label = label_from_path(dasd_file) if dasd_file else ""

        if mounted != self._mounted or vol_label != self._vol_label:
            self._mounted = mounted
            self._vol_label = vol_label

    # ── Workspace ─────────────────────────────────────────────────────────────

    def create_workspace(self, parent: QWidget) -> QWidget:
        if self._workspace is None:
            self._workspace, self._output = create_command_output_workspace(parent)
        return self._workspace

    def on_selected(self, api_client=None) -> None:
        """Run WORKSPACE_COMMANDS and display their output."""
        if self._output is None:
            return
        client = api_client or self._api
        if client is None:
            return

        render_workspace_commands(self._output, client, WORKSPACE_COMMANDS, devnum=self.devnum)

    def get_buttons(self) -> list[ButtonDef]:
        return []

    # ── Room overlay ──────────────────────────────────────────────────────────

    def draw_room_overlay(self, painter: QPainter, rect: QRect) -> None:
        """
        Draw disc overlay and volume label when a volume is mounted.
        rect is the dest_rect of the device bitmap in the room canvas.
        """
        if not self._mounted:
            return

        if self._disc_pixmap is not None:
            target = QRect(
                rect.left() + _DISC_RECT.left(),
                rect.top()  + _DISC_RECT.top(),
                _DISC_RECT.width(),
                _DISC_RECT.height(),
            )
            painter.drawPixmap(target, self._disc_pixmap)

        if self._vol_label:
            text_rect = QRect(
                rect.left() + _TEXT_X0,
                rect.top()  + _TEXT_Y0,
                _TEXT_RIGHT - _TEXT_X0,
                _TEXT_BOTTOM - _TEXT_Y0,
            )
            font = QFont()
            font.setPixelSize(9)
            painter.save()
            painter.setFont(font)
            painter.setPen(_TEXT_COLOR)
            painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, self._vol_label)
            painter.restore()

    def room_light_levels(self) -> Optional[list[float]]:
        return [
            self.room_connected_light(),
            self.room_activity_level(),
            self.room_state_light(False),
            self.room_state_light(self._mounted),
        ]
