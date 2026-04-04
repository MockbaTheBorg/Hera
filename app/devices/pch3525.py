# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Hera IBM 3525 Card Punch device plugin.

Handles devclass="PCH".  Receives punched card data from Hercules via a
sockdev TCP connection and accumulates lines into a read-only card deck.
The operator can view the deck as card images or as text, and save or
discard the output.
"""

import logging
from typing import Optional

import shiboken6
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QMessageBox, QWidget,
)

from ..device_base import ButtonDef, DeviceContext
from ..socket_reader import SocketLineReader as SocketReader
from .card_device_base import BaseCardDeckDevice
from .card_data import DEFAULT_LANGUAGE

logger = logging.getLogger(__name__)


class Pch3525Device(BaseCardDeckDevice):
    """IBM 3525 Card Punch device plugin."""

    device_classes = ["PCH"]
    bitmap_name    = "3525.png"
    room_light_origin = (79, 25)
    config_prefix = "pch"
    default_color = "PAPER"
    default_language = DEFAULT_LANGUAGE
    initial_mode = "card"
    read_only = True

    def __init__(
        self,
        context: Optional[DeviceContext] = None,
    ):
        super().__init__(context)

        # Socket reader (started in create_workspace)
        self._reader: Optional[SocketReader] = None
        self._btn_connect = None
        self._btn_disconnect = None
        self._disconnect_dlg = None
        self._skip_separator_cards = True

    # ── DeviceBase interface ──────────────────────────────────────────────────

    def create_workspace(self, parent: QWidget) -> QWidget:
        first_create = self._container is None
        widget = self._create_deck_container(parent)
        if first_create and self._port:
            self._reader = SocketReader(
                self._host,
                self._port,
                thread_name=f"CardSocketReader:{self._port}",
                logger=logger,
                recv_timeout=1.0,
            )
            self._reader.line_received.connect(self._on_line_received)
            self._reader.connected_changed.connect(self._on_connection_changed)
            self._reader.start()
        return widget

    def get_buttons(self) -> list[ButtonDef]:
        return [
            ButtonDef(label="Setup",       callback=self._do_setup),
            ButtonDef(label="Discard",     callback=self._do_discard),
            ButtonDef(label="Save",        callback=self._do_save),
            ButtonDef(
                label=self._toggle_button_label(),
                callback=self._do_toggle_view,
                on_created=lambda b: setattr(self, '_toggle_btn', b),
            ),
            ButtonDef(label="Socket", is_label=True),
            ButtonDef(
                label="Connect",
                callback=self._do_connect,
                on_created=self._on_connect_button_created,
            ),
            ButtonDef(
                label="Disconnect",
                callback=self._do_disconnect,
                on_created=self._on_disconnect_button_created,
            ),
        ]

    def cleanup(self) -> None:
        if self._reader is not None:
            self._reader.stop()

    def _skip_separator_key(self) -> str:
        return f"{self.config_prefix}_skip_separator_{self._devnum}"

    def _load_persisted_settings(self) -> None:
        super()._load_persisted_settings()
        if self._config is not None:
            self._skip_separator_cards = self._config.get_setting("devices", self._skip_separator_key(), "1") == "1"

    def _apply_setup(self) -> None:
        values = self._run_setup_dialog(skip_separator_cards=self._skip_separator_cards)
        if values is None:
            return
        self._apply_setup_values(values)
        new_skip_separator = bool(values.skip_separator_cards)
        if new_skip_separator != self._skip_separator_cards:
            self._skip_separator_cards = new_skip_separator
            self._set_persisted_setting(
                self._skip_separator_key(),
                "1" if new_skip_separator else "0",
            )

    def room_light_levels(self) -> Optional[list[float]]:
        loaded = self.room_state_light(self._deck_view is not None and bool(self._deck_view.lines))
        return [self.room_connected_light(), self.room_activity_level(), self.room_state_light(False), loaded]

    def _looks_like_separator_card(self, line: str) -> bool:
        stripped = line.rstrip()
        if len(stripped) < 40:
            return False
        normalized = stripped.replace("þ", "Þ")
        pipe_count = normalized.count("|")
        if pipe_count < 20 or not normalized.startswith("|"):
            return False
        if any(ch in normalized for ch in ("/", "*", " ")):
            return False

        punch_art_chars = {"|", "Þ"}
        for ch in normalized:
            if ch in punch_art_chars:
                continue
            if "a" <= ch.lower() <= "z":
                punch_art_chars.add(ch)
                continue
            return False

        distinct_letters = {ch.lower() for ch in normalized if ch.isalpha() and ch.lower() != "þ"}
        return len(distinct_letters) <= 6 and "Þ" in normalized

    def _update_connection_buttons(self) -> None:
        connected = bool(self._reader is not None and self._reader.is_connected)
        if self._btn_connect is not None and shiboken6.isValid(self._btn_connect):
            self._btn_connect.setEnabled(not connected)
        else:
            self._btn_connect = None
        if self._btn_disconnect is not None and shiboken6.isValid(self._btn_disconnect):
            self._btn_disconnect.setEnabled(connected)
        else:
            self._btn_disconnect = None

    def _on_connect_button_created(self, button) -> None:
        self._btn_connect = button
        self._update_connection_buttons()

    def _on_disconnect_button_created(self, button) -> None:
        self._btn_disconnect = button
        self._update_connection_buttons()

    @Slot(bool)
    def _on_connection_changed(self, connected: bool) -> None:
        self._update_connection_buttons()

    def _do_connect(self) -> None:
        if self._reader is not None:
            self._reader.connect_socket()
        self._update_connection_buttons()

    def _do_disconnect(self) -> None:
        dlg = QMessageBox(
            QMessageBox.Icon.Question,
            "Disconnect Punch",
            "Disconnect the puncher socket connection?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self._container,
        )
        dlg.setDefaultButton(QMessageBox.StandardButton.No)
        dlg.accepted.connect(self._on_disconnect_accepted)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        self._disconnect_dlg = dlg
        dlg.open()

    def _on_disconnect_accepted(self) -> None:
        self._disconnect_dlg = None
        if self._reader is not None:
            self._reader.disconnect_socket()

    # ── Socket line handler ───────────────────────────────────────────────────

    @Slot(str)
    def _on_line_received(self, line: str) -> None:
        """Receive one card from Hercules; right-pad/truncate to 80 chars."""
        if self._deck_view is None:
            return
        if self._skip_separator_cards and not self._deck_view.lines and self._looks_like_separator_card(line):
            return
        self.mark_room_activity()
        # Pad to 80 or truncate; append_line also calls _renumber()
        card = line[:80].ljust(80)
        self._deck_view.append_line(card)
        self._deck_view.changed = True

    # ── Button callbacks ──────────────────────────────────────────────────────

    def _do_setup(self) -> None:
        self._apply_setup()

    def _do_discard(self) -> None:
        if self._deck_view is None:
            return
        if not self._deck_view.lines:
            return  # Nothing to discard
        if self._deck_view.changed and not self._confirm(
            "Discard Deck",
            "The deck has unsaved cards. Discard all cards?",
        ):
            return
        self._deck_view.clear()

    def _do_save(self) -> bool:
        if self._deck_view is None:
            return False
        if not self._deck_view.lines:
            return False  # No-op on empty deck
        return self._save_deck()

    def _do_toggle_view(self) -> None:
        self._toggle_view()
