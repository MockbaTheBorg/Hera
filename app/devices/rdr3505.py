# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Hera IBM 3505 Card Reader device plugin.

Handles devclass="RDR".  Provides a writable 80-column card deck editor for
authoring JCL/FORTRAN/ASM/plain-text jobs; submits to Hercules via a raw TCP
socket to the pre-configured sockdev port.
"""

import logging
import socket
import threading
from typing import Optional

import shiboken6
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog, QMessageBox, QPushButton, QWidget,
)

from ..device_base import ButtonDef, DeviceContext
from .card_device_base import BaseCardDeckDevice
from .card_data import DEFAULT_LANGUAGE, language_for_path

logger = logging.getLogger(__name__)

class _SubmitSignals(QObject):
    """Helper QObject so the submit thread can signal back to the main thread."""
    done  = Signal()
    error = Signal(str)


class Rdr3505Device(BaseCardDeckDevice):
    """IBM 3505 Card Reader device plugin."""

    device_classes = ["RDR"]
    bitmap_name    = "3505.png"
    room_light_origin = (135, 25)
    config_prefix = "rdr"
    default_color = "PAPER"
    default_language = DEFAULT_LANGUAGE
    initial_mode = "editor"
    read_only = False

    def __init__(
        self,
        context: Optional[DeviceContext] = None,
    ):
        super().__init__(context)
        self._submit_btn: Optional[QPushButton]  = None

        # Thread-safe signals for submit completion
        self._sig = _SubmitSignals()
        self._sig.done.connect(self._on_submit_done)
        self._sig.error.connect(self._on_submit_error)

    # ── DeviceBase interface ──────────────────────────────────────────────────

    def create_workspace(self, parent: QWidget) -> QWidget:
        return self._create_deck_container(parent)

    def get_buttons(self) -> list[ButtonDef]:
        self._submit_btn = None
        return [
            ButtonDef(label="Setup",     callback=self._do_setup),
            ButtonDef(label="New",       callback=self._do_new),
            ButtonDef(label="Load",      callback=self._do_load),
            ButtonDef(label="Save",      callback=self._do_save),
            ButtonDef(
                label=self._toggle_button_label(),
                callback=self._do_toggle_view,
                on_created=lambda b: setattr(self, '_toggle_btn', b),
            ),
            ButtonDef(label="Submit",    callback=self._do_submit,
                      on_created=lambda b: setattr(self, '_submit_btn', b)),
        ]

    # ── Button callbacks ──────────────────────────────────────────────────────

    def _do_setup(self) -> None:
        self._apply_setup()

    def _do_new(self) -> None:
        if self._deck_view is None:
            return
        if self._deck_view.changed and not self._confirm(
            "New Deck",
            "The deck has unsaved changes. Discard and create a new deck?",
        ):
            return
        self._deck_view.clear()

    def _do_load(self) -> None:
        if self._deck_view is None:
            return
        if self._deck_view.changed and not self._confirm(
            "Load Deck",
            "The deck has unsaved changes. Discard and load a file?",
        ):
            return
        path, _ = QFileDialog.getOpenFileName(
            self._deck_view,
            "Load Card Deck",
            "",
            "Card files (*.jcl *.for *.asm *.txt);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="latin-1") as fh:
                raw_lines = fh.read().splitlines()
        except Exception as exc:
            QMessageBox.critical(self._deck_view, "Load Error", str(exc))
            return
        loaded_lang = language_for_path(path)
        self._lang = loaded_lang
        self._deck_view.set_language(loaded_lang)
        self._set_persisted_setting(self._lang_key(), loaded_lang)
        # set_lines pads/truncates each line to 80 chars
        self._deck_view.set_lines(raw_lines)
        self._deck_view.changed = False

    def _do_save(self) -> bool:
        return self._save_deck()

    def _do_toggle_view(self) -> None:
        self._toggle_view()

    def _do_submit(self) -> None:
        if self._deck_view is None or self._port == 0:
            return
        lines = list(self._deck_view.lines)
        if not lines:
            return

        self._set_submit_enabled(False)

        sig = self._sig

        def _send():
            try:
                with socket.create_connection((self._host, self._port), timeout=10) as sock:
                    for line in lines:
                        sock.sendall((line.rstrip() + "\r\n").encode("latin-1"))
                sig.done.emit()
            except Exception as exc:
                sig.error.emit(str(exc))

        threading.Thread(target=_send, daemon=True,
                         name=f"Rdr3505Submit:{self._port}").start()

    @Slot()
    def _on_submit_done(self) -> None:
        self.mark_room_activity()
        if self._deck_view is not None:
            self._deck_view.changed = False
        self._set_submit_enabled(True)

    @Slot(str)
    def _on_submit_error(self, error: str) -> None:
        self._set_submit_enabled(True)
        QMessageBox.critical(
            self._deck_view,
            "Submit Failed",
            f"Could not connect to port {self._port}:\n{error}",
        )

    def _set_submit_enabled(self, enabled: bool) -> None:
        if self._submit_btn is not None and shiboken6.isValid(self._submit_btn):
            self._submit_btn.setEnabled(enabled)
        else:
            self._submit_btn = None
