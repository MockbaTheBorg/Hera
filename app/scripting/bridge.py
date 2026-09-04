# Hera - Hercules Hyperion GUI - by Mockba the Borg
#
"""Cross-thread call bridge for the scripting API.

The HTTP server runs in its own daemon thread. Any code that touches a
QWidget must run on the Qt GUI thread. MainThreadBridge marshals a callable
onto the GUI thread using the same Qt queued-signal mechanism the rest of
Hera already relies on for background-to-GUI updates (e.g.
ConsoleWorkspace._update_display), and blocks the calling thread until the
callable has run (or timed out).
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QWidget


@dataclass
class _PendingCall:
    fn: Callable[[], Any]
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    exception: BaseException | None = None


class MainThreadBridge(QObject):
    """Created on the GUI thread; callable from any thread."""

    run_call = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.run_call.connect(self._on_run_call, Qt.QueuedConnection)
        # Inert, never-shown parent for widgets the API needs to exist (e.g.
        # a card deck view) without bringing anything to the front.
        self.headless_parent = QWidget()

    @Slot(object)
    def _on_run_call(self, pending: _PendingCall) -> None:
        try:
            pending.result = pending.fn()
        except BaseException as exc:  # re-raised on the calling thread below
            pending.exception = exc
        finally:
            pending.event.set()

    def call_on_gui_thread(self, fn: Callable[[], Any], timeout: float = 5.0) -> Any:
        """Run fn() on the GUI thread and return its result, from any thread."""
        pending = _PendingCall(fn=fn)
        self.run_call.emit(pending)
        if not pending.event.wait(timeout):
            raise TimeoutError("Scripting API call timed out waiting for the GUI thread")
        if pending.exception is not None:
            raise pending.exception
        return pending.result
