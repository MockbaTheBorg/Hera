# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
PrinterWorkspace — reusable workspace widget for line-printer and console-printer
devices (IBM 1403, 3215).

Contains a GreenBarPaper scrolling area and optionally a command input bar.
Save and Discard operations are exposed as plain methods so the device plugin
can wire them to ButtonDef callbacks.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout,
)
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt, Signal, Slot

from .command_input import CommandInputBar
from .green_bar_paper import GreenBarPaper


class PrinterWorkspace(QWidget):
    """
    Workspace for line-printer devices.

    Parameters
    ----------
    font_family      : font family name passed to GreenBarPaper
    bar_even         : even-line band color (default: white)
    bar_odd          : odd-line band color (default: #DDFFDD)
    lines_per_band   : lines sharing the same band color (default: 1)
    has_command_input: when True adds a Hercules command bar below the paper
    page_length      : lines per page for perforation markers (default: 66)
    """

    send_command = Signal(str)
    _update_display = Signal(list, bool)  # (lines, full_refresh) — thread-safe

    def __init__(
        self,
        parent=None,
        font_family: str = "",
        bar_even: QColor = None,
        bar_odd: QColor = None,
        has_command_input: bool = False,
        page_length: int = 66,
        color_name: str = "GREEN",
    ):
        super().__init__(parent)
        self._has_cmd = has_command_input
        self._font_family = font_family
        self._bar_even = bar_even
        self._bar_odd = bar_odd
        self._page_length = page_length
        self._color_name = color_name

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._paper = GreenBarPaper(
            bar_even=bar_even,
            bar_odd=bar_odd,
            font_family=font_family,
            page_length=page_length,
        )
        layout.addWidget(self._paper, stretch=1)

        if has_command_input:
            self._command_bar = CommandInputBar(self)
            self._command_bar.send_command.connect(self.send_command)
            layout.addWidget(self._command_bar)
        else:
            self._command_bar = None

        # Queued connection keeps _apply_update on the main thread
        self._update_display.connect(self._apply_update, Qt.ConnectionType.QueuedConnection)

    def _append_lines(self, lines: list) -> None:
        for line in lines:
            if line is not None:
                self._paper.append_line(str(line))

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(list, bool)
    def _apply_update(self, lines: list, full_refresh: bool) -> None:
        if full_refresh:
            self._paper.set_lines(lines)
        else:
            self._append_lines(lines)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def focus_input(self) -> None:
        """Set keyboard focus to the command field (no-op when no command input)."""
        if self._command_bar is not None:
            self._command_bar.focus_input()

    def do_discard(self) -> None:
        """Clear all paper content."""
        self._paper.set_lines([])
