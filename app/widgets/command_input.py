# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Shared command-input widgets.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


class HistoryLineEdit(QLineEdit):
    """QLineEdit subclass that adds Up/Down arrow key history navigation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: list[str] = []
        self._history_pos: int = -1
        self._saved_input: str = ""

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Up:
            self._navigate(1)
        elif key == Qt.Key_Down:
            self._navigate(-1)
        else:
            super().keyPressEvent(event)

    def _navigate(self, direction: int):
        if not self._history:
            return
        if self._history_pos == -1 and direction == 1:
            self._saved_input = self.text()
        new_pos = self._history_pos + direction
        if new_pos < 0:
            self._history_pos = -1
            self.setText(self._saved_input)
            self._saved_input = ""
            return
        self._history_pos = min(len(self._history) - 1, new_pos)
        self.setText(self._history[-(self._history_pos + 1)])

    def add_to_history(self, cmd: str):
        if not self._history or cmd != self._history[-1]:
            self._history.append(cmd)
        self._history_pos = -1

    def current_command(self) -> str:
        return self.text().strip()


class CommandInputBar(QWidget):
    """Reusable command-entry bar with history and a Send button."""

    send_command = Signal(str)

    def __init__(self, parent=None, placeholder: str = "hercules command..."):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._cmd_input = HistoryLineEdit()
        self._cmd_input.setPlaceholderText(placeholder)
        self._cmd_input.returnPressed.connect(self._send)
        layout.addWidget(self._cmd_input, stretch=1)

        send_btn = QPushButton("Send")
        send_btn.setFixedHeight(28)
        send_btn.setFixedWidth(60)
        send_btn.clicked.connect(self._send)
        layout.addWidget(send_btn)

    def _send(self) -> None:
        cmd = self._cmd_input.current_command()
        if not cmd:
            return
        self._cmd_input.add_to_history(cmd)
        self._cmd_input.clear()
        self.send_command.emit(cmd)

    def focus_input(self) -> None:
        self._cmd_input.setFocus()
