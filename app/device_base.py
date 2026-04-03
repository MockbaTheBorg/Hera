# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Device plugin base class and generic fallback for Hera.

All device plugins must inherit DeviceBase and implement the required methods.
GenericDevice is used for devices with no matching plugin.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import time
from typing import Optional, Callable

from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtGui import QPainter, QColor
from PySide6.QtCore import QRect, Qt

from .theme import BUTTON_HEIGHT  # re-exported for backwards compatibility

import os as _os

_BITMAPS_BASE = _os.path.join(_os.path.dirname(__file__), "bitmaps")
_bitmap_theme: str = "blue"


def set_bitmap_theme(theme: str) -> None:
    """Set the active bitmap theme (subdirectory under app/bitmaps/)."""
    global _bitmap_theme
    _bitmap_theme = theme.strip() or "blue"


def bitmaps_dir() -> str:
    """Return the path to the active bitmap theme directory."""
    return _os.path.join(_BITMAPS_BASE, _bitmap_theme)


@dataclass
class ButtonDef:
    """Definition for a button in the device button column."""
    label: str
    callback: Optional[Callable] = None
    icon_path: Optional[str] = None
    tooltip: Optional[str] = None
    enabled: bool = True
    on_created: Optional[Callable] = None  # called with the QPushButton after creation
    is_label: bool = False
    full_width: bool = False


@dataclass
class DeviceContext:
    """Structured inputs used to construct all device instances."""
    devclass: str = ""
    devnum: str = ""
    devtype: str = ""
    label: str = ""
    api_client: object | None = None
    devport: int = 0
    config: object | None = None
    host: str = "127.0.0.1"


STATE_PANEL_W = 25
STATE_PANEL_H = 7
STATE_LIGHT_INSET = 1
STATE_LIGHT_SIZE = 5
_STATE_ON_COLORS = (
    QColor(255, 176, 176),
    QColor(176, 255, 176),
    QColor(176, 255, 176),
    QColor(224, 224, 144),
)


class DeviceBase(ABC):
    """
    Abstract base class for all Hera device plugins.

    Each device plugin provides:
    - Room rendering: bitmap name + optional overlay drawing
    - Workspace: the main content widget shown in the device area
    - Buttons: entries for the fixed button column
    - Polling: periodic API data refresh
    - Lifecycle: selection/deselection notifications

    Workspace lifecycle default:
    - create the workspace once per device instance and reuse it
    - only recreate it when the device has a documented reason to do so
    """

    # Class-level attributes that subclasses should set
    device_classes: list[str] = []   # Hercules devclass values this plugin handles (e.g. ["DSP"])
    bitmap_name: str = "unknown.png"  # Filename in bitmaps/ directory
    background_color: QColor = QColor(166, 202, 240)  # Default room background
    room_light_origin: Optional[tuple[int, int]] = None

    def __init__(self, context: Optional[DeviceContext] = None):
        """
        Args:
            devnum    : Device address from Hercules (e.g. "0700"), or "" for non-addressed devices
            devtype   : Device type number (e.g. "3270")
            label     : Display label for the room slot tab
            api_client: HerculesAPI instance (optional; used by devices that need API access at init)
            devport   : Per-device socket port extracted from the API device listing (0 = not set)
        """
        self.context = context or DeviceContext()
        self.devclass = self.context.devclass
        self.devnum = self.context.devnum
        self.devtype = self.context.devtype
        self.devport = self.context.devport
        self.host = self.context.host
        self.api_client = self.context.api_client
        self.config = self.context.config
        self.label = self.context.label or self._default_label()
        self._room_device_info: Optional[dict] = None
        self._last_room_activity_at: float = 0.0
        self._room_repaint_callback: Optional[Callable] = None

    def _default_label(self) -> str:
        if self.devnum:
            return f"{self.devtype} at {self.devnum}"
        return self.__class__.__name__

    @abstractmethod
    def create_workspace(self, parent: QWidget) -> QWidget:
        """Return the widget to display in the device workspace area."""
        ...

    @abstractmethod
    def get_buttons(self) -> list[ButtonDef]:
        """Return the list of button definitions for the button column."""
        ...

    def draw_room_overlay(self, painter: QPainter, rect: QRect) -> None:
        """
        Draw an overlay on top of the device bitmap in the room area.
        Default implementation draws nothing.
        Override to add blinkenlights, mini screens, etc.
        """
        pass

    def set_room_device_info(self, info: Optional[dict]) -> None:
        """Cache the latest REST device row for room-light decisions."""
        self._room_device_info = info

    def room_device_info(self) -> Optional[dict]:
        """Return the latest REST device row for this device, if available."""
        return self._room_device_info

    def request_room_repaint(self) -> None:
        """Ask the room widget to repaint this device's slot immediately."""
        if self._room_repaint_callback is not None:
            self._room_repaint_callback()

    def mark_room_activity(self) -> None:
        """Record recent device activity for transient lamp pulses."""
        self._last_room_activity_at = time.monotonic()

    def room_activity_level(self, decay_s: float = 1.2) -> float:
        """Return a 0..1 intensity for recent activity."""
        if self._last_room_activity_at <= 0.0:
            return 0.0
        age = time.monotonic() - self._last_room_activity_at
        if age >= decay_s:
            return 0.0
        return max(0.0, 1.0 - (age / decay_s))

    def room_light_levels(self) -> Optional[list[float]]:
        """
        Return four Jason-style lamp intensities:
        online, activity, attention, open/media.
        """
        return None

    def draw_room_lights(self, painter: QPainter, rect: QRect) -> None:
        """Draw Jason-style square room lights when configured by the device."""
        origin = self.room_light_origin
        levels = self.room_light_levels()
        if origin is None or not levels:
            return

        # All lights off when Hercules is disconnected
        if self.room_device_info() is None:
            levels = [0.0] * len(levels)

        dx = (STATE_PANEL_W - 1) // 4
        painter.save()
        for i, on_color in enumerate(_STATE_ON_COLORS):
            level = max(0.0, min(1.0, float(levels[i] if i < len(levels) else 0.0)))
            off_color = QColor(
                on_color.red() // 4 + 16,
                on_color.green() // 4 + 16,
                on_color.blue() // 4 + 16,
            )
            color = QColor(
                int(off_color.red() + (on_color.red() - off_color.red()) * level),
                int(off_color.green() + (on_color.green() - off_color.green()) * level),
                int(off_color.blue() + (on_color.blue() - off_color.blue()) * level),
            )
            painter.fillRect(
                rect.left() + origin[0] + i * dx + STATE_LIGHT_INSET,
                rect.top() + origin[1] + STATE_LIGHT_INSET,
                STATE_LIGHT_SIZE,
                STATE_LIGHT_SIZE,
                color,
            )
        painter.restore()

    def poll(self, api_client) -> None:
        """
        Called periodically by the main polling worker.
        Use api_client to fetch data and update internal state only.

        Threading contract:
        - poll() may run off the UI thread
        - poll() must not touch QWidget instances directly
        - if UI changes are needed, emit a signal and apply them in the main thread
        """
        pass

    def button_column_width(self) -> int:
        """Return the desired button column width in pixels. Override to change from default."""
        return 120

    def button_columns(self) -> int:
        """Return the number of button columns. Override for multi-column layouts."""
        return 1

    def create_button_widget(self, parent: QWidget) -> Optional[QWidget]:
        """Return an optional custom widget for the button column."""
        return None

    def has_button_column_content(self) -> bool:
        """Return True when the device wants the button column shown."""
        return bool(self.get_buttons())

    def cleanup(self) -> None:
        """Release background resources (threads, sockets, etc.).
        Called by MainWindow before replacing the device list.
        Override in plugins that hold long-lived resources."""
        pass

    def on_selected(self, api_client=None) -> None:
        """Called when this device is selected in the room."""
        pass

    def on_deselected(self) -> None:
        """Called when another device is selected."""
        pass

    def on_app_closing(self) -> None:
        """Called during application shutdown before device cleanup."""
        pass


DEVCLASS_BITMAP = {
    "TAPE": "2401.png",
    "DASD": "2311.png",
    "DSP":  "3270.png",
    "PRT":  "1403.png",
    "RDR":  "3505.png",
    "PCH":  "3525.png",
}


class GenericDevice(DeviceBase):
    """
    Fallback device for unimplemented device types.
    Shows a placeholder workspace and no buttons.
    """

    device_classes: list[str] = []  # Never auto-matched
    bitmap_name: str = "unknown.png"

    def __init__(self, context: Optional[DeviceContext] = None):
        super().__init__(context)
        # Try to use a matching bitmap if available
        self._pick_bitmap(self.devtype, self.devclass)

    def _pick_bitmap(self, devtype: str, devclass: str = ""):
        """Select the best available bitmap for this device type."""
        d = bitmaps_dir()
        candidate = f"{devtype.lower()}.png"
        if _os.path.exists(_os.path.join(d, candidate)):
            self.bitmap_name = candidate
        elif devclass and devclass in DEVCLASS_BITMAP:
            fallback = DEVCLASS_BITMAP[devclass]
            if _os.path.exists(_os.path.join(d, fallback)):
                self.bitmap_name = fallback

    def create_workspace(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)
        msg = QLabel(
            f"Device {self.devtype} at {self.devnum}\nnot yet implemented",
            widget
        )
        msg.setAlignment(Qt.AlignCenter)
        msg.setStyleSheet("color: #888888; font-size: 14px;")
        layout.addWidget(msg)
        return widget

    def get_buttons(self) -> list[ButtonDef]:
        return []
