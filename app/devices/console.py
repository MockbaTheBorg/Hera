# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Hera Console device plugin.

Displays the Hercules system log (syslog) in a green-on-black scrolling
text area with a command input and Send button at the bottom of the workspace.
The Console represents the Hercules operator console (not a 3270 terminal).
"""
from typing import Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit
from PySide6.QtGui import QPainter, QTextCursor, QColor, QTextCharFormat
from PySide6.QtCore import Qt, QRect, Signal, Slot

from ..device_base import DeviceBase, ButtonDef, DeviceContext
from .terminal_colors import console_bg_color, console_fg_color, CONSOLE_LINE_HIGHLIGHTS
from ..widgets.command_input import CommandInputBar
from ..widgets.mini_screen import MiniScreenOverlay
from ..widgets.terminal_style import CONSOLE_FONT_SIZE_PX, terminal_font_family
from ..theme import WORKSPACE_FRAME, SCROLLBAR_QSS

# Console screen area within console.png bitmap (in bitmap-relative coords)
# From Jason's devimg table: listx0=24, listy0=9, listdx=71, listdy=52
MINI_SCREEN_X = 21
MINI_SCREEN_Y = 7
MINI_SCREEN_W = 76
MINI_SCREEN_H = 55

# Mini-screen content window — 80×24 matches a 3270 model 2 screen.
MINI_SCREEN_LINES = 25
MINI_SCREEN_COLS  = 80
MINI_SCREEN_OPACITY = 0.5   # 0.0 = fully transparent, 1.0 = fully opaque
MINI_SCREEN_BRIGHTNESS_BOOST = 1.35


class ConsoleWorkspace(QWidget):
    """Green-on-black syslog display with command input bar at the bottom."""

    send_command = Signal(str)
    _update_display = Signal(list, bool)  # (lines, full_refresh) — emitted from poll thread

    def __init__(self, parent=None, *, fg_color: QColor | None = None, font_family: str | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        fg = fg_color or console_fg_color(None)
        font_family = font_family or terminal_font_family()

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "QTextEdit {"
            f" background-color: {console_bg_color().name()};"
            f" color: {fg.name()};"
            f" font-family: '{font_family}', monospace;"
            f" font-size: {CONSOLE_FONT_SIZE_PX}px;"
            f" border: {WORKSPACE_FRAME};"
            " }"
            + SCROLLBAR_QSS
        )
        self._log.setLineWrapMode(QTextEdit.NoWrap)
        layout.addWidget(self._log, stretch=1)

        self._command_bar = CommandInputBar(self)
        self._command_bar.send_command.connect(self.send_command)
        layout.addWidget(self._command_bar)

        # Queued connection ensures _apply_update always runs in the main thread
        # even when _update_display is emitted from the poll worker thread.
        self._update_display.connect(self._apply_update, Qt.QueuedConnection)

    def focus_input(self):
        self._command_bar.focus_input()

    @Slot(list, bool)
    def _apply_update(self, lines: list, full_refresh: bool):
        """Called in the main thread via queued connection."""
        if full_refresh:
            self.set_lines(lines)
        else:
            self.append_lines(lines)

    def append_lines(self, lines: list[str]):
        """Append new syslog lines and auto-scroll to bottom."""
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.End)
        default_fmt = QTextCharFormat()
        for line in lines:
            if line:
                fmt = default_fmt
                for pattern, fg, bg in CONSOLE_LINE_HIGHLIGHTS:
                    if pattern.match(line):
                        fmt = QTextCharFormat()
                        if fg is not None:
                            fmt.setForeground(fg)
                        if bg is not None:
                            fmt.setBackground(bg)
                        break
                cursor.setCharFormat(fmt)
                cursor.insertText(line + "\n")
        cursor.setCharFormat(default_fmt)
        self._log.setTextCursor(cursor)
        self._log.ensureCursorVisible()

    def set_lines(self, lines: list[str]):
        """Replace all content (used for initial load or full refresh)."""
        self._log.clear()
        self.append_lines(lines)


class ConsoleDevice(DeviceBase):
    """
    Hercules operator console device plugin.
    Handles device class "CONSOLE" (the special Hercules log device).
    """

    device_classes = ["CONSOLE"]
    bitmap_name = "console.png"

    def __init__(self, context: Optional[DeviceContext] = None):
        super().__init__(context)
        self._workspace: Optional[ConsoleWorkspace] = None
        self._mini_lines: list[str] = []   # Last few lines for room overlay
        self._pending_command: Optional[str] = None
        self._workspace_initialized: bool = False
        self._fg_color = console_fg_color(self.config)
        self._font_family = terminal_font_family()
        self._mini_screen = MiniScreenOverlay(
            MINI_SCREEN_X, MINI_SCREEN_Y, MINI_SCREEN_W, MINI_SCREEN_H,
            max_lines=MINI_SCREEN_LINES,
            max_cols=MINI_SCREEN_COLS,
            fg_color=self._fg_color,
            bg_color=console_bg_color(),
            font_family=self._font_family,
            bold=True,
            opacity=MINI_SCREEN_OPACITY,
            brightness_boost=MINI_SCREEN_BRIGHTNESS_BOOST,
        )

    @staticmethod
    def _nonempty_lines(lines: list[str] | None) -> list[str]:
        return [line for line in (lines or []) if line]

    def _emit_workspace_lines(self, lines: list[str], *, full_refresh: bool) -> None:
        if self._workspace is not None and lines:
            self._workspace._update_display.emit(lines, full_refresh)

    def _apply_polled_lines(self, lines: list[str]) -> None:
        if not lines:
            return
        self._mini_lines = (self._mini_lines + lines)[-MINI_SCREEN_LINES:]
        if self._workspace is None:
            return
        full_refresh = not self._workspace_initialized
        self._emit_workspace_lines(lines, full_refresh=full_refresh)
        self._workspace_initialized = True

    def create_workspace(self, parent: QWidget) -> QWidget:
        if self._workspace is None:
            self._workspace = ConsoleWorkspace(
                parent,
                fg_color=self._fg_color,
                font_family=self._font_family,
            )
            self._workspace.send_command.connect(self._on_send_command)
            self._workspace_initialized = False
        return self._workspace

    def get_buttons(self) -> list[ButtonDef]:
        return []

    def _on_send_command(self, cmd: str):
        self._pending_command = cmd

    def poll(self, api_client) -> None:
        """Fetch syslog lines and update workspace display."""
        cmd = self._pending_command
        self._pending_command = None

        if cmd:
            api_client.syslog_feed.send_command(cmd)

        lines = api_client.syslog_feed.pull_new()
        if lines is None:
            # API failure — reset so next successful call does a full refresh
            self._workspace_initialized = False
            return
        self._apply_polled_lines(self._nonempty_lines(lines))

    def draw_room_overlay(self, painter: QPainter, rect: QRect) -> None:
        """Render a scaled-down representation of the console log into the room mini-screen."""
        self._mini_screen.render(painter, rect, self._mini_lines, highlights=CONSOLE_LINE_HIGHLIGHTS)

    def on_selected(self, api_client=None) -> None:
        if self._workspace is not None:
            self._workspace.focus_input()
        client = api_client or self.api_client
        if self._workspace is None or client is None:
            return
        if self._workspace_initialized:
            return
        lines = self._nonempty_lines(client.syslog_feed.get_all())
        if not lines:
            return
        self._mini_lines = lines[-MINI_SCREEN_LINES:]
        self._emit_workspace_lines(lines, full_refresh=True)
        self._workspace_initialized = True
