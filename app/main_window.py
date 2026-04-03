# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Main window for Hera.

Layout (top to bottom):
  - Menu bar
  - Room area (310px fixed height, scrollable)
  - Device area (workspace + button column, stretches)
  - Status bar

Polling is driven by a QTimer in the main thread, with API calls
dispatched to a background QThread worker.
"""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QStatusBar, QMessageBox, QLabel
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject, Slot
from PySide6.QtGui import QAction

from .config import Config, VERSION_MAJOR, VERSION_MINOR
from .api_client import HerculesAPI
from .room_widget import RoomWidget
from .device_area import DeviceArea
from .device_base import DeviceBase

logger = logging.getLogger(__name__)

MIN_WIDTH = 1080
MIN_HEIGHT = 840


class PollerWorker(QObject):
    """
    Background worker that calls poll() on all devices each tick.
    Runs in a QThread to avoid blocking the UI.
    """

    finished = Signal()
    connection_changed = Signal(bool)  # True = connected, False = disconnected
    poll_done = Signal(int)            # Device index after each device poll

    def __init__(self, api: HerculesAPI):
        super().__init__()
        self._api = api
        self._devices: list[DeviceBase] = []
        self._was_connected = False

    def set_devices(self, devices: list[DeviceBase]):
        self._devices = devices

    @Slot()
    def run(self):
        """Run one poll cycle in the worker thread.

        Device poll() implementations must treat this as a background thread and
        avoid touching QWidget objects directly.
        """
        # Check connectivity
        connected = self._api.test_connection()
        if connected != self._was_connected:
            self._was_connected = connected
            self.connection_changed.emit(connected)

        device_rows = {}
        if connected:
            result = self._api.get_devices()
            if result:
                device_rows = {
                    dev.get("devnum", ""): dev
                    for dev in result.get("devices", [])
                    if dev.get("devnum", "")
                }

        for i, device in enumerate(self._devices):
            try:
                device.set_room_device_info(device_rows.get(device.devnum) if device.devnum else None)
                device.poll(self._api)
            except Exception as e:
                logger.warning("Device poll error [%d]: %s", i, e)
            self.poll_done.emit(i)

        self.finished.emit()


class MainWindow(QMainWindow):
    _start_poll = Signal()

    def __init__(self, config: Config, api: HerculesAPI, devices: list[DeviceBase],
                 device_builder=None):
        super().__init__()
        self._config = config
        self._api = api
        self._devices = devices
        self._device_builder = device_builder  # callable() -> list[DeviceBase]
        self._active_device: Optional[DeviceBase] = None
        self._connected = False
        self._poll_in_flight = False
        self._shutting_down = False
        self._pending_rebuild = False

        self._setup_window()
        self._setup_menu()
        self._setup_central()
        self._setup_statusbar()
        self._setup_polling()
        self._restore_geometry()

        # Populate room
        self._room.set_devices(devices)

        # Initial version fetch
        self._fetch_version()

    def _connection_text(self, connected: bool) -> str:
        state = "Connected to" if connected else "Disconnected"
        return f"{state} {self._config.host}:{self._config.port}" if connected else f"{state} ({self._config.host}:{self._config.port})"

    def _run_device_hook(self, method_name: str, devices: Optional[list[DeviceBase]] = None, *,
                         log_message: str) -> None:
        for dev in devices if devices is not None else self._devices:
            try:
                getattr(dev, method_name)()
            except Exception as exc:
                logger.warning(log_message, exc)

    def _setup_window(self):
        self.setWindowTitle(f"Hera v{VERSION_MAJOR}.{VERSION_MINOR}")
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        self.resize(self._config.window_width, self._config.window_height)

    def _setup_menu(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_central(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._room = RoomWidget()
        self._room.device_selected.connect(self._on_device_selected)
        layout.addWidget(self._room)

        self._device_area = DeviceArea()
        layout.addWidget(self._device_area, stretch=1)

    def _setup_statusbar(self):
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._conn_label = QLabel("Connecting...")
        self._version_label = QLabel("")
        self._status_bar.addWidget(self._conn_label)
        self._status_bar.addPermanentWidget(self._version_label)
        self._update_status_disconnected()

    def _setup_polling(self):
        self._poll_thread = QThread()
        self._poller = PollerWorker(self._api)
        self._poller.moveToThread(self._poll_thread)
        self._start_poll.connect(self._poller.run, Qt.QueuedConnection)
        self._poller.connection_changed.connect(self._on_connection_changed)
        self._poller.poll_done.connect(self._room.refresh_slot)
        self._poller.finished.connect(self._on_poll_finished)
        self._poll_thread.start()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._trigger_poll)
        self._timer.start(int(self._config.poll_interval * 1000))

    def _trigger_poll(self):
        if self._poll_in_flight:
            return
        self._poll_in_flight = True
        self._poller.set_devices(self._devices)
        self._start_poll.emit()

    @Slot()
    def _on_poll_finished(self):
        self._poll_in_flight = False
        if self._pending_rebuild and self._connected and not self._shutting_down:
            self._pending_rebuild = False
            self._rebuild_devices()

    def _restore_geometry(self):
        if self._config.window_x >= 0 and self._config.window_y >= 0:
            self.move(self._config.window_x, self._config.window_y)

    def _save_geometry(self):
        pos = self.pos()
        size = self.size()
        self._config.window_x = pos.x()
        self._config.window_y = pos.y()
        self._config.window_width = size.width()
        self._config.window_height = size.height()
        self._config.save()

    def _fetch_version(self):
        data = self._api.get_version()
        if data:
            ver = data.get("hercules_version", "")
            modes = ", ".join(data.get("modes", []))
            self._version_label.setText(f"Hercules {ver} | {modes}")

    @Slot(int)
    def _on_device_selected(self, index: int):
        if 0 <= index < len(self._devices):
            self._active_device = self._devices[index]
            self._device_area.select_device(self._active_device)
            button_column = self._device_area.get_button_column()
            btn_widget = self._active_device.create_button_widget(button_column)
            if btn_widget is not None:
                button_column.clear()
                button_column.add_widget(btn_widget)
            self._device_area.set_visible(self._active_device.has_button_column_content())
            self._active_device.on_selected(self._api)

    @Slot(bool)
    def _on_connection_changed(self, connected: bool):
        if self._shutting_down:
            return
        self._connected = connected
        if connected:
            self._update_status_connected()
            # Defer full device rebuild until the current poll cycle has finished.
            self._pending_rebuild = self._device_builder is not None
            if not self._pending_rebuild:
                self._room.set_devices(self._devices)
        else:
            self._update_status_disconnected()

    def _rebuild_devices(self) -> None:
        if self._device_builder is None:
            return

        if self._active_device is not None:
            try:
                self._active_device.on_deselected()
            except Exception as exc:
                logger.warning("Active device deselect failed during rebuild: %s", exc)
        self._active_device = None

        self._device_area.show_placeholder()
        self._room.set_devices([])

        old_devices = self._devices
        self._devices = []
        self._poller.set_devices([])
        self._run_device_hook("cleanup", old_devices, log_message="Device cleanup failed during rebuild: %s")

        self._devices = self._device_builder()
        self._poller.set_devices(self._devices)
        self._room.set_devices(self._devices)

    def _update_status_connected(self):
        self._conn_label.setText(self._connection_text(True))
        self._conn_label.setStyleSheet("color: green;")

    def _update_status_disconnected(self):
        self._conn_label.setText(self._connection_text(False))
        self._conn_label.setStyleSheet("color: red;")

    def _show_about(self):
        QMessageBox.about(
            self,
            "About Hera",
            f"<b>Hera v{VERSION_MAJOR}.{VERSION_MINOR}</b><br><br>"
            "Hera makes Hercules do things.<br><br>"
            "Graphical interface for the Hercules IBM mainframe emulator.<br>"
            "Based on Jason by Oleh Yuschuk (2010).<br><br>"
            "Targets SDL Hyperion Hercules via REST API.<br><br>"
            "Author: Mockba the Borg"
        )

    def closeEvent(self, event):
        self._shutting_down = True
        self._timer.stop()
        self._poller.set_devices([])
        self._poll_thread.quit()
        if not self._poll_thread.wait(5000):
            logger.warning("Polling thread did not stop cleanly before shutdown")
        self._run_device_hook("on_app_closing", log_message="Device shutdown save failed: %s")
        self._run_device_hook("cleanup", log_message="Device cleanup failed during shutdown: %s")
        self._save_geometry()
        super().closeEvent(event)
