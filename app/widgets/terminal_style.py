# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Shared font and color helpers for terminal-like widgets.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics


_TERMINAL_FONT_FILE = Path(__file__).resolve().parent.parent / "fonts" / "terminal.ttf"
_TERMINAL_FONT_FAMILY: str | None = None
_FONT_LOAD_ATTEMPTED = False

CONSOLE_DEFAULT_FG = QColor("#00CC00")
CONSOLE_DEFAULT_BG = QColor("#000000")
TERMINAL_FALLBACK_FAMILY = "Courier New"
CONSOLE_FONT_SIZE_PX = 16
DSP3270_FONT_SIZE_PX = 17
TERMINAL_MINI_FONT_SIZE_PX = 16


def terminal_font_family() -> str:
    global _TERMINAL_FONT_FAMILY, _FONT_LOAD_ATTEMPTED
    if _TERMINAL_FONT_FAMILY is not None:
        return _TERMINAL_FONT_FAMILY
    if not _FONT_LOAD_ATTEMPTED:
        _FONT_LOAD_ATTEMPTED = True
        if _TERMINAL_FONT_FILE.exists():
            font_id = QFontDatabase.addApplicationFont(str(_TERMINAL_FONT_FILE))
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    _TERMINAL_FONT_FAMILY = families[0]
    return _TERMINAL_FONT_FAMILY or TERMINAL_FALLBACK_FAMILY


def terminal_font(pixel_size: int = CONSOLE_FONT_SIZE_PX) -> QFont:
    font = QFont(terminal_font_family())
    font.setPixelSize(pixel_size)
    return font


def console_color_from_string(raw: str) -> QColor:
    color = QColor(raw)
    if color.isValid():
        return color
    return QColor(CONSOLE_DEFAULT_FG)


def fit_terminal_font_to_cell(
    *,
    target_cell_w: int,
    target_cell_h: int,
    default_pixel_size: int = DSP3270_FONT_SIZE_PX,
) -> tuple[QFont, int]:
    """
    Return a terminal font that fits within an existing cell geometry.

    The returned tuple is (font, ascent). The caller keeps using the provided
    target cell width/height, which preserves the workspace footprint.
    """
    best = terminal_font(default_pixel_size)
    best_metrics = QFontMetrics(best)
    if best_metrics.horizontalAdvance("M") <= target_cell_w and best_metrics.height() <= target_cell_h:
        return best, min(best_metrics.ascent(), target_cell_h - 1)

    for size in range(default_pixel_size - 1, 5, -1):
        candidate = terminal_font(size)
        metrics = QFontMetrics(candidate)
        if metrics.horizontalAdvance("M") <= target_cell_w and metrics.height() <= target_cell_h:
            return candidate, min(metrics.ascent(), target_cell_h - 1)

    return best, min(best_metrics.ascent(), target_cell_h - 1)
