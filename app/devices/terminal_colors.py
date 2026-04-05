# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Shared terminal color helpers for console-like devices.
"""

import re

from PySide6.QtGui import QColor

from ..widgets.terminal_style import CONSOLE_DEFAULT_FG, CONSOLE_DEFAULT_BG, console_color_from_string

# Regex-based line highlight rules for the console workspace and mini-screen overlay.
# Each entry is (compiled_pattern, fg_color | None, bg_color | None).
# Rules are evaluated in order; the first match wins.
# Either color may be None to keep the channel at its default.
CONSOLE_LINE_HIGHLIGHTS: list[tuple[re.Pattern, QColor | None, QColor | None]] = [
    (re.compile(r"^HHC\d{5}W"), QColor("#FFFFFF"), QColor("#FF8C00")),   # warning → orange fg
    (re.compile(r"^HHC\d{5}E"), QColor("#FFFFFF"), QColor("#FF4444")),   # error   → red fg
]


def console_fg_color(config) -> QColor:
    if config is None:
        return QColor(CONSOLE_DEFAULT_FG)
    raw = config.get_setting("devices", "console_text_color", CONSOLE_DEFAULT_FG.name())
    return console_color_from_string(raw)


def console_bg_color() -> QColor:
    return QColor(CONSOLE_DEFAULT_BG)
