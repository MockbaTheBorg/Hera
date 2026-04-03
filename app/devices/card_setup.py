# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Setup helpers for card devices.
"""

import os

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
)
from .card_data import LANGUAGES

_CARDS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "bitmaps", "cards")
)


def discover_card_colors() -> list[str]:
    """Scan the card bitmap directory and return uppercase color names."""
    try:
        names = []
        for fname in sorted(os.listdir(_CARDS_DIR)):
            if fname.startswith("card_") and fname.endswith(".png"):
                color = fname[len("card_"):-len(".png")].upper()
                if color:
                    names.append(color)
        return names
    except OSError:
        return []


class CardSetupDialog(QDialog):
    """Setup dialog for card color and language mode."""

    def __init__(
        self,
        color: str,
        lang: str,
        auto_number: bool,
        *,
        skip_separator_cards: bool | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Card Setup")
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setContentsMargins(8, 8, 8, 8)
        form.setSpacing(10)

        colors = discover_card_colors()
        self._color_cb = QComboBox()
        self._color_cb.addItems(colors)
        self._color_cb.setCurrentText(color if color in colors else (colors[0] if colors else ""))
        form.addRow("Card color:", self._color_cb)

        self._lang_cb = QComboBox()
        self._lang_cb.addItems(LANGUAGES)
        self._lang_cb.setCurrentText(lang if lang in LANGUAGES else "JCL")
        form.addRow("Language:", self._lang_cb)

        self._auto_number_cb = QCheckBox("Automatically number sequence columns")
        self._auto_number_cb.setChecked(auto_number)
        form.addRow("", self._auto_number_cb)

        self._skip_separator_cb: QCheckBox | None = None
        if skip_separator_cards is not None:
            self._skip_separator_cb = QCheckBox("Skip leading separator cards")
            self._skip_separator_cb.setChecked(skip_separator_cards)
            form.addRow("", self._skip_separator_cb)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def color(self) -> str:
        return self._color_cb.currentText()

    @property
    def lang(self) -> str:
        return self._lang_cb.currentText()

    @property
    def auto_number(self) -> bool:
        return self._auto_number_cb.isChecked()

    @property
    def skip_separator_cards(self) -> bool:
        return bool(self._skip_separator_cb is not None and self._skip_separator_cb.isChecked())
