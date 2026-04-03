# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Shared base helpers for card-deck devices.
"""

from dataclasses import dataclass
from typing import Optional

from PySide6.QtWidgets import QFileDialog, QFrame, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ..device_base import DeviceBase, DeviceContext
from ..theme import WORKSPACE_FRAME
from .card_common import CardDeckView
from .card_data import LANGUAGES, lang_ext
from .card_setup import CardSetupDialog


@dataclass(frozen=True)
class CardSetupValues:
    color: str
    lang: str
    auto_number: bool
    skip_separator_cards: bool | None = None


class BaseCardDeckDevice(DeviceBase):
    """Shared behavior for editable/read-only card deck devices."""

    default_color = "BEIGE"
    default_language = "JCL"
    config_prefix = ""
    initial_mode = "editor"
    read_only = False

    def __init__(self, context: Optional[DeviceContext] = None):
        super().__init__(context)
        self._port = self.devport
        self._host = self.host or "127.0.0.1"
        self._devnum = self.devnum
        self._config = self.config
        self._deck_view: Optional[CardDeckView] = None
        self._container: Optional[QFrame] = None
        self._toggle_btn: Optional[QPushButton] = None

        self._color = self.default_color
        self._lang = self.default_language
        self._auto_number = False
        self._load_persisted_settings()

    def _color_key(self) -> str:
        return f"{self.config_prefix}_color_{self._devnum}"

    def _lang_key(self) -> str:
        return f"{self.config_prefix}_lang_{self._devnum}"

    def _load_persisted_settings(self) -> None:
        if self._config is None:
            return
        color = self._config.get_setting("devices", self._color_key(), self.default_color)
        if color:
            self._color = color
        lang = self._config.get_setting("devices", self._lang_key(), self.default_language)
        if lang in LANGUAGES:
            self._lang = lang
        auto_number = self._config.get_setting("devices", self._auto_number_key(), "0")
        self._auto_number = auto_number == "1"

    def _auto_number_key(self) -> str:
        return f"{self.config_prefix}_auto_number_{self._devnum}"

    def _create_deck_view(self) -> CardDeckView:
        return CardDeckView(
            initial_mode=self.initial_mode,
            read_only=self.read_only,
            color=self._color,
            lang=self._lang,
            auto_number=self._auto_number,
            parent=None,
        )

    def _create_deck_container(self, parent: QWidget) -> QWidget:
        if self._container is None:
            self._deck_view = self._create_deck_view()
            self._container = QFrame()
            self._container.setFrameStyle(QFrame.Shape.NoFrame)
            self._container.setStyleSheet(f"QFrame {{ border: {WORKSPACE_FRAME}; }}")
            layout = QVBoxLayout(self._container)
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(0)
            layout.addWidget(self._deck_view)
        self._container.setParent(parent)
        return self._container

    def _set_persisted_setting(self, key: str, value: str) -> None:
        if self._config is not None:
            self._config.set_setting("devices", key, value)

    def _apply_setup_values(self, values: CardSetupValues) -> None:
        if values.color != self._color:
            self._color = values.color
            if self._deck_view is not None:
                self._deck_view.set_color(values.color)
            self._set_persisted_setting(self._color_key(), values.color)

        if values.lang != self._lang:
            self._lang = values.lang
            if self._deck_view is not None:
                self._deck_view.set_language(values.lang)
            self._set_persisted_setting(self._lang_key(), values.lang)

        if values.auto_number != self._auto_number:
            self._auto_number = values.auto_number
            if self._deck_view is not None:
                self._deck_view.set_auto_number(values.auto_number)
            self._set_persisted_setting(
                self._auto_number_key(),
                "1" if values.auto_number else "0",
            )

    def _run_setup_dialog(self, *, skip_separator_cards: bool | None = None) -> Optional[CardSetupValues]:
        dlg = CardSetupDialog(
            color=self._color,
            lang=self._lang,
            auto_number=self._auto_number,
            skip_separator_cards=skip_separator_cards,
            parent=self._deck_view,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return None
        return CardSetupValues(
            color=dlg.color,
            lang=dlg.lang,
            auto_number=dlg.auto_number,
            skip_separator_cards=dlg.skip_separator_cards if skip_separator_cards is not None else None,
        )

    def _apply_setup(self) -> None:
        values = self._run_setup_dialog()
        if values is not None:
            self._apply_setup_values(values)

    def _confirm(self, title: str, message: str) -> bool:
        parent = self._deck_view or self._container
        reply = QMessageBox.question(
            parent,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _save_deck(self) -> bool:
        if self._deck_view is None:
            return False
        ext = lang_ext(self._lang)
        path, _ = QFileDialog.getSaveFileName(
            self._deck_view,
            "Save Card Deck",
            "",
            f"Card files (*{ext});;All files (*)",
        )
        if not path:
            return False
        if not path.lower().endswith(ext):
            path += ext
        try:
            with open(path, "w", encoding="latin-1", newline="") as fh:
                for line in self._deck_view.lines:
                    fh.write(line + "\n")
            self._deck_view.changed = False
            return True
        except Exception as exc:
            QMessageBox.critical(self._deck_view, "Save Error", str(exc))
            return False

    def _toggle_view(self) -> None:
        if self._deck_view is None:
            return
        if self._deck_view.mode == "card":
            self._deck_view.set_mode("editor")
            if self._toggle_btn is not None:
                self._toggle_btn.setText("Card view")
        else:
            self._deck_view.set_mode("card")
            if self._toggle_btn is not None:
                self._toggle_btn.setText("Editor view")

    def _toggle_button_label(self) -> str:
        if self._deck_view and self._deck_view.mode == "editor":
            return "Card view"
        return "Editor view"

    def room_light_levels(self) -> Optional[list[float]]:
        connected = 1.0 if self.room_device_info() is not None else 0.0
        changed = 1.0 if (self._deck_view is not None and self._deck_view.changed) else 0.0
        loaded = 1.0 if (self._deck_view is not None and bool(self._deck_view.lines)) else 0.0
        return [connected, self.room_activity_level(), changed, loaded]
