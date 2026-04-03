#!/usr/bin/env python3
# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Hera — Graphical interface for the Hercules IBM mainframe emulator.
Connects to a running SDL Hyperion Hercules instance via REST API.

Usage:
    python main.py [--host HOST] [--port PORT]
"""

import logging
import os
import re
import sys

from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle
from PySide6.QtGui import QColor
from PySide6.QtCore import QRect, QLoggingCategory

from app.theme import SCROLLBAR_EXTENT


class _ScrollBarStyle(QProxyStyle):
    """Custom scrollbar appearance: light-gray handle on dark track.

    Uses QProxyStyle (paint override) instead of a CSS stylesheet so the
    cascade never touches any other widget — no palette side-effects.
    """

    _TRACK  = QColor(0x2d, 0x2d, 0x2d)
    _HANDLE = QColor(0x88, 0x88, 0x88)

    def drawComplexControl(self, control, option, painter, widget=None):
        if control != QStyle.CC_ScrollBar:
            super().drawComplexControl(control, option, painter, widget)
            return
        # Track
        painter.fillRect(option.rect, self._TRACK)
        # Handle
        handle = self.subControlRect(QStyle.CC_ScrollBar, option,
                                     QStyle.SC_ScrollBarSlider, widget)
        if handle.isValid() and not handle.isEmpty():
            painter.fillRect(handle.adjusted(1, 1, -1, -1), self._HANDLE)
        # Arrow buttons and page areas are intentionally not drawn

    def subControlRect(self, control, option, subControl, widget=None):
        if control == QStyle.CC_ScrollBar and subControl in (
            QStyle.SC_ScrollBarAddLine, QStyle.SC_ScrollBarSubLine
        ):
            return QRect()   # zero-size → hidden arrows
        return super().subControlRect(control, option, subControl, widget)

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PM_ScrollBarExtent:
            return SCROLLBAR_EXTENT
        if metric == QStyle.PM_ScrollBarSliderMin:
            return 20        # minimum handle length
        return super().pixelMetric(metric, option, widget)

from app.config import Config, parse_args, VERSION_MAJOR, VERSION_MINOR
from app.device_base import set_bitmap_theme
from app.api_client import HerculesAPI
from app.device_registry import DeviceRegistry
from app.main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# fontTools is extremely verbose at INFO — it logs every glyph during font
# subsetting whenever a PDF is saved.  Silence it to ERROR.
logging.getLogger("fontTools").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


def _extract_devport(assignment: str) -> int:
    """Return the sockdev port from a Hercules assignment string."""
    match = re.match(r"[^:\s]+:(\d+)", assignment or "")
    return int(match.group(1)) if match else 0


def _device_label(devclass: str, devtype: str, devnum: str, devport: int) -> str:
    """Build the room label for a discovered device."""
    if devport == 3215:
        return f"CON 3215 at {devnum}"
    return f"{devclass} {devtype} at {devnum}" if devnum else devclass


def _mute_wayland_qpa_logs() -> None:
    """Silence noisy Wayland QPA logs before QApplication startup."""
    rules = [
        "qt.qpa.wayland.debug=false",
        "qt.qpa.wayland.info=false",
        "qt.qpa.wayland.warning=false",
        "qt.qpa.wayland.textinput.debug=false",
        "qt.qpa.wayland.textinput.info=false",
        "qt.qpa.wayland.textinput.warning=false",
    ]
    existing = os.environ.get("QT_LOGGING_RULES", "").strip()
    merged = "\n".join(([existing] if existing else []) + rules)
    QLoggingCategory.setFilterRules(merged)


def build_device_list(api: HerculesAPI, registry: DeviceRegistry, config=None):
    """
    Discover devices from the Hercules API and create plugin instances.
    The CPU and Console are always first (not address-based).
    """
    devices = []

    # Console is always present (Hercules log)
    devices.append(registry.create_console_device(api_client=api, config=config))

    # CPU is always present
    devices.append(registry.create_cpu_device(api_client=api, config=config))

    # Auto-discover address-based devices from the API
    result = api.get_devices() or {}
    for dev in result.get("devices", []):
        devclass = dev.get("devclass", "")
        devnum = dev.get("devnum", "")
        devtype = dev.get("devtype", "")
        devport = _extract_devport(dev.get("assignment", ""))
        devices.append(
            registry.create_device(
                devclass=devclass,
                devnum=devnum,
                devtype=devtype,
                label=_device_label(devclass, devtype, devnum, devport),
                api_client=api,
                devport=devport,
                config=config,
            )
        )

    return devices


def main():
    args = parse_args()

    config = Config()
    config.load()
    config.apply_args(args)
    set_bitmap_theme(config.bitmap_theme)

    _mute_wayland_qpa_logs()

    app = QApplication(sys.argv)
    app.setApplicationName("Hera")
    app.setApplicationVersion(f"{VERSION_MAJOR}.{VERSION_MINOR}")

    app.setStyle(_ScrollBarStyle())

    # Set up API client
    api = HerculesAPI(base_url=config.api_base_url)

    # Test connectivity (non-fatal — show disconnected state)
    if not api.test_connection():
        logger.warning("Hercules not reachable at %s", config.api_base_url)

    # Load device plugins
    registry = DeviceRegistry()
    loaded = registry.load()
    logger.info("Loaded %d device plugin(s): %s", loaded, registry.registered_classes)

    # Launch main window
    window = MainWindow(
        config=config,
        api=api,
        devices=[],
        device_builder=lambda: build_device_list(api, registry, config),
    )
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
