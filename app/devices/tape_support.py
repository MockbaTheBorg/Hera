# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Support helpers and dialogs for tape devices.
"""

import os
import re
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout,
)

from ..theme import DIALOG_MIN_WIDTH

_HERC_PREFIX = re.compile(r"^HHC\d{5}[A-Z]\s+")
_VOLSER_RE = re.compile(r"^[A-Z0-9$#@]+$")
_ALNUM = re.compile(r"^[A-Z0-9]+$")
_DISPLAY_TEXT_RE = re.compile(r'"([^"]*)"')


@dataclass(frozen=True)
class TapeDisplayState:
    primary_text: str = ""
    secondary_text: Optional[str] = None
    mode: str = "static"


def _dialog_buttons(parent, accept, reject) -> QDialogButtonBox:
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=parent)
    buttons.accepted.connect(accept)
    buttons.rejected.connect(reject)
    return buttons


def _warning(parent, message: str) -> None:
    QMessageBox.warning(parent, "Validation", message)


def validate_folder(folder: str) -> str:
    """Strip leading '.' and '/' chars; fall back to 'tapes' if empty."""
    folder = folder.strip()
    while folder and folder[0] in (".", "/"):
        folder = folder.lstrip("./").lstrip("/")
    return folder or "tapes"


def validate_tape_filename(filename: str) -> Optional[str]:
    """Normalize and validate a user-supplied tape filename."""
    filename = filename.strip()
    if not filename:
        return None
    if not os.path.splitext(filename)[1]:
        filename += ".aws"
    if os.path.isabs(filename):
        return None
    normalised = os.path.normpath(filename)
    if normalised.startswith(".."):
        return None
    return normalised


def strip_herc_prefix(line: str) -> str:
    return _HERC_PREFIX.sub("", line).rstrip()


def parse_display(assignment: str) -> TapeDisplayState:
    _, sep, tail = assignment.partition("Display:")
    if not sep:
        return TapeDisplayState()

    texts = [text.strip() for text in _DISPLAY_TEXT_RE.findall(tail)]
    if not texts:
        return TapeDisplayState()

    mode = "static"
    lowered = tail.lower()
    if "(alternating)" in lowered:
        mode = "alternating"
    elif "(blinking)" in lowered:
        mode = "blinking"

    primary_text = texts[0]
    secondary_text = texts[1] if len(texts) > 1 else None
    if mode == "alternating" and not secondary_text:
        mode = "static"

    return TapeDisplayState(primary_text=primary_text, secondary_text=secondary_text, mode=mode)


def parse_assignment(assignment: str):
    """Return (file_path, is_protected, display_state) for a tape assignment."""
    display_state = parse_display(assignment)
    stripped = assignment.strip()
    if not stripped or stripped.startswith("*"):
        return None, False, display_state

    file_path = None
    is_protected = False
    for tok in stripped.split():
        if tok in {"ro", "*FP*"}:
            is_protected = True
        elif tok.startswith("["):
            continue
        elif tok == "Display:":
            break
        elif file_path is None:
            file_path = tok

    return file_path, is_protected, display_state


class MountDialog(QDialog):
    """File picker for mounting a tape."""

    def __init__(self, files: list, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog)
        self.setMinimumWidth(DIALOG_MIN_WIDTH)
        self.setWindowTitle("Mount Tape")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Select tape file:"))
        self._combo = QComboBox()
        self._combo.addItems(files)
        layout.addWidget(self._combo)

        self._ro_check = QCheckBox("Mount Read-Only (default)")
        self._ro_check.setChecked(True)
        layout.addWidget(self._ro_check)

        layout.addWidget(_dialog_buttons(self, self.accept, self.reject))

    def selected_file(self) -> str:
        return self._combo.currentText()

    def is_readonly(self) -> bool:
        return self._ro_check.isChecked()


class NewTapeDialog(QDialog):
    """Form for creating a new tape file."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog)
        self.setMinimumWidth(DIALOG_MIN_WIDTH)
        self.setWindowTitle("Create New Tape")
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._filename = QLineEdit()
        self._filename.setPlaceholderText("e.g. newtape  or  special/newtape.aws")
        form.addRow("Filename:", self._filename)

        self._volser = QLineEdit()
        self._volser.setMaxLength(6)
        self._volser.setPlaceholderText("Required - A-Z 0-9 $ # @")
        form.addRow("VOLSER *:", self._volser)

        self._owner = QLineEdit()
        self._owner.setMaxLength(8)
        self._owner.setPlaceholderText("Optional - letters and numbers only")
        form.addRow("Owner:", self._owner)

        layout.addLayout(form)

        layout.addWidget(_dialog_buttons(self, self._validate_and_accept, self.reject))

    def _validate_and_accept(self):
        filename = self._filename.text().strip()
        volser = self._volser.text().strip().upper()
        owner = self._owner.text().strip().upper()

        if not filename:
            _warning(self, "Filename is required.")
            return
        if validate_tape_filename(filename) is None:
            _warning(self, "Invalid filename.\nPath must stay within the tapes folder.")
            return
        if not volser:
            _warning(self, "VOLSER is required.")
            return
        if not _VOLSER_RE.match(volser):
            _warning(self, "VOLSER must contain only letters, digits, $, #, or @.")
            return
        if owner and not _ALNUM.match(owner):
            _warning(self, "Owner must contain only letters and numbers.")
            return
        self.accept()

    def filename(self) -> str:
        return validate_tape_filename(self._filename.text().strip())

    def volser(self) -> str:
        return self._volser.text().strip().upper()

    def owner(self) -> str:
        return self._owner.text().strip().upper()
