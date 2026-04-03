# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Hera UI theme — central source for all global UI constants.

Devices and widgets import defaults from here and may shadow them locally
when an intentional deviation is needed (add a comment explaining why).

This module MUST NOT import from any other app/ module (circular import risk).
Only stdlib and Qt imports are permitted here.
"""

from PySide6.QtGui import QColor


# ── Layout ─────────────────────────────────────────────────────────────────────

BUTTON_HEIGHT        = 32    # Standard button height for device button columns
BUTTON_BORDER_RADIUS = 4     # Rounded corner radius for all application buttons (px)
BUTTON_COLUMN_WIDTH  = 120   # Default device button column width (px)
BUTTON_SPACING       = 6     # Vertical gap between buttons in the button column

ROOM_CONTENT_HEIGHT  = 306   # Room content area: 28px label tab + 278px tallest bitmap
ROOM_SCROLLBAR_H     = 10    # Strip reserved for the horizontal scrollbar below the room
ROOM_HEIGHT          = ROOM_CONTENT_HEIGHT + ROOM_SCROLLBAR_H  # 316px total

SCROLLBAR_EXTENT     = 10    # Width / height of all application scrollbars (px)

# QSS scrollbar rules that replicate _ScrollBarStyle for QTextEdit widgets.
# When a QTextEdit has a stylesheet applied, Qt's QSS engine takes over its
# child scrollbars and ignores the application QProxyStyle.  Appending these
# rules to the widget stylesheet restores the intended appearance.
SCROLLBAR_QSS = (
    " QScrollBar:vertical   { background: #2d2d2d; width:  10px; border: none; }"
    " QScrollBar::handle:vertical   { background: #888888; min-height: 20px; margin: 0px; }"
    " QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
    " QScrollBar:horizontal { background: #2d2d2d; height: 10px; border: none; }"
    " QScrollBar::handle:horizontal { background: #888888; min-width:  20px; margin: 0px; }"
    " QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }"
)
DIALOG_MIN_WIDTH     = 380   # Minimum width for popup dialogs — ensures title is never clipped


# ── Colors ─────────────────────────────────────────────────────────────────────

BUTTON_DEFAULT_BG = "#6d6d6d"      # Default button background (raised against device area)
BUTTON_DEFAULT_FG = "#e8e8e8"      # Default button text color

DEVICE_AREA_BG   = "#505050"       # Device area panel background
PANEL_BG         = "#808080"       # Gray panel background (CPU workspace, console)
PANEL_FG         = "#1a1a1a"       # Near-black text on gray panel backgrounds
WORKSPACE_BG     = "#ffffff"       # Default output-workspace background
WORKSPACE_FG     = "#000000"       # Default output-workspace text color
WORKSPACE_BORDER = "1px solid #333333"  # Standard border around workspace output widgets
WORKSPACE_FRAME  = "1px solid #999999"  # Decorative frame matching the printer workspace border

# Room slot background — stored as tuple to avoid constructing QColor before QApplication.
# Use room_bg_color() to get a QColor instance.
#ROOM_BG = (166, 202, 240)
ROOM_BG = (157, 168, 155)

def room_bg_color() -> QColor:
    """Return the default room slot background as a QColor."""
    return QColor(*ROOM_BG)


def _adjust_hex_color(hex_color: str, factor: float) -> str:
    """Lighten (factor > 1.0) or darken (factor < 1.0) a #rrggbb color string."""
    h = hex_color.lstrip('#')
    r = min(255, max(0, int(int(h[0:2], 16) * factor)))
    g = min(255, max(0, int(int(h[2:4], 16) * factor)))
    b = min(255, max(0, int(int(h[4:6], 16) * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def _gradient_bg(color: str) -> str:
    """Return a qlineargradient CSS value for a raised-look button.

    Hex colors (#rrggbb) get a top-to-bottom gradient: 25% lighter at top,
    15% darker at bottom.  Non-hex formats (e.g. rgb(...)) are returned as-is
    for a flat fill.
    """
    if color.startswith('#'):
        light = _adjust_hex_color(color, 1.25)
        dark  = _adjust_hex_color(color, 0.85)
        return f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {light}, stop:1 {dark})"
    return color


def _pressed_bg(color: str) -> str:
    """Return a pressed-state background for buttons.

    Hex colors keep the same palette but flip to a darker top-to-bottom
    gradient so the button feels pressed instead of raised.
    """
    if color.startswith('#'):
        top = _adjust_hex_color(color, 0.90)
        bottom = _adjust_hex_color(color, 0.70)
        return f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {top}, stop:1 {bottom})"
    return color


def button_style(
    bg: str = BUTTON_DEFAULT_BG,
    fg: str = BUTTON_DEFAULT_FG,
    border_color: str = "#505050",
    border_width: int = 1,
    checked_bg: str = None,
    checked_border: str = None,
    font_size: int = None,
    bold: bool = False,
    extra: str = "",
) -> str:
    """Return a complete QPushButton stylesheet string.

    ALL button creation in the application MUST use this function so that
    rounded corners, border, and color are applied uniformly.
    Do not inject BUTTON_BORDER_RADIUS directly into inline stylesheets.

    Hex bg colors (#rrggbb) produce a top-to-bottom gradient (25% lighter top,
    15% darker bottom) to simulate a raised appearance.  Non-hex formats use
    a flat fill so prt1403 colour-swatch buttons retain their exact hue.

    Args:
        bg:             Button background color.
        fg:             Button text color.
        border_color:   Border color (1px solid by default).
        border_width:   Border width in px.
        checked_bg:     Background for :checked state (checkable buttons only).
        checked_border: Border color for :checked state (defaults to border_color).
        font_size:      Font size in px (omitted if None — inherits).
        bold:           Whether to apply font-weight: bold.
        extra:          Additional CSS rules appended verbatim (e.g. ":hover {...}").
    """
    size_part = f" font-size: {font_size}px;" if font_size else ""
    bold_part = " font-weight: bold;" if bold else ""
    style = (
        f"QPushButton {{"
        f" background: {_gradient_bg(bg)}; color: {fg};"
        f" border: {border_width}px solid {border_color};"
        f" border-radius: {BUTTON_BORDER_RADIUS}px;"
        f" padding: 2px 4px;"
        f"{size_part}{bold_part} }}"
    )
    style += (
        f" QPushButton:pressed {{"
        f" background: {_pressed_bg(bg)};"
        f" border-color: {_adjust_hex_color(border_color, 0.75) if border_color.startswith('#') else border_color};"
        f" padding-top: 3px; padding-left: 5px; padding-bottom: 1px; padding-right: 3px; }}"
    )
    style += (
        f" QPushButton:disabled {{"
        f" background: {_gradient_bg('#3a3a3a')}; color: #555555;"
        f" border-color: #444444; }}"
    )
    if checked_bg:
        cb = checked_border or border_color
        style += (f" QPushButton:checked {{"
                  f" background: {_gradient_bg(checked_bg)}; border-color: {cb}; }}")
    if extra:
        style += f" {extra}"
    return style


# ── Fonts ──────────────────────────────────────────────────────────────────────

WORKSPACE_FONT_FAMILY = "Monospace"   # Default font family for output workspace widgets
WORKSPACE_FONT_SIZE   = 9             # Default font size (pt) for output workspace widgets
