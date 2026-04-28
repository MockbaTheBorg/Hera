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

import inspect
import logging
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QDialog, QMainWindow, QWidget, QVBoxLayout,
    QProgressDialog, QStatusBar, QMessageBox, QLabel
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject, Slot
from PySide6.QtGui import QAction

from .config import (
    Config,
    VERSION_MAJOR,
    VERSION_MINOR,
    normalize_room_background,
    parse_device_order,
)
from .api_client import HerculesAPI
from .room_widget import RoomWidget
from .device_area import DeviceArea
from .device_base import DeviceBase, set_bitmap_theme
from .preferences_dialog import PreferencesDialog

logger = logging.getLogger(__name__)

MIN_WIDTH = 1080
MIN_HEIGHT = 840


class ShutdownProgressDialog:
    """Small modal progress dialog for printer PDF saves during shutdown."""

    def __init__(self, parent: QWidget | None):
        self._dialog = QProgressDialog(parent)
        self._dialog.setWindowTitle("Saving Printer PDFs")
        self._dialog.setCancelButton(None)
        self._dialog.setMinimumDuration(0)
        self._dialog.setAutoClose(False)
        self._dialog.setAutoReset(False)
        self._dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._dialog.setRange(0, 0)
        self._dialog.hide()

    def update(self, label: str, current: int, total: int) -> None:
        total = max(1, int(total))
        current = max(0, min(int(current), total))
        self._dialog.setLabelText(f"{label}\nPage {current} of {total}")
        self._dialog.setRange(0, total)
        self._dialog.setValue(current)
        if not self._dialog.isVisible():
            self._dialog.show()
        QApplication.processEvents()

    def close(self) -> None:
        if not self._dialog.isVisible():
            return
        self._dialog.setValue(self._dialog.maximum())
        self._dialog.close()
        QApplication.processEvents()


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

    def reset_connection_state(self, connected: bool = False) -> None:
        self._was_connected = connected

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
        self._base_devices = list(devices)
        self._devices = self._sort_devices_by_config(self._base_devices)
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
        self._room.set_devices(self._devices)

        # Initial version fetch
        self._fetch_version()

    def _connection_text(self, connected: bool) -> str:
        state = "Connected to" if connected else "Disconnected"
        return f"{state} {self._config.host}:{self._config.port}" if connected else f"{state} ({self._config.host}:{self._config.port})"

    def _run_device_hook(self, method_name: str, devices: Optional[list[DeviceBase]] = None, *,
                         log_message: str, **hook_kwargs) -> None:
        for dev in devices if devices is not None else self._devices:
            try:
                method = getattr(dev, method_name)
                signature = inspect.signature(method)
                accepts_var_kwargs = any(
                    parameter.kind == inspect.Parameter.VAR_KEYWORD
                    for parameter in signature.parameters.values()
                )
                if accepts_var_kwargs:
                    method(**hook_kwargs)
                else:
                    filtered_kwargs = {
                        name: value
                        for name, value in hook_kwargs.items()
                        if name in signature.parameters
                    }
                    method(**filtered_kwargs)
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
        preferences_action = QAction("&Preferences", self)
        preferences_action.setShortcut("Ctrl+,")
        preferences_action.triggered.connect(self._show_preferences)
        file_menu.addAction(preferences_action)
        file_menu.addSeparator()

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
        self._room.set_room_background(self._config.room_background)
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

    def _sort_devices_by_config(self, devices: list[DeviceBase]) -> list[DeviceBase]:
        order = self._config.device_order
        if not order:
            return list(devices)
        order_index = {devclass: index for index, devclass in enumerate(order)}
        default_index = len(order)
        indexed_devices = sorted(
            enumerate(devices),
            key=lambda item: (order_index.get(item[1].devclass, default_index), item[0]),
        )
        return [device for _, device in indexed_devices]

    def _refresh_room_from_current_devices(self) -> None:
        selected_device = self._active_device
        self._devices = self._sort_devices_by_config(self._base_devices)
        self._poller.set_devices(self._devices)
        self._room.set_devices(self._devices, selected_device=selected_device, emit_selection=False)

    def _on_bitmap_theme_changed(self) -> None:
        for device in self._base_devices:
            try:
                device.on_bitmap_theme_changed()
            except Exception as exc:
                logger.warning("Device bitmap theme refresh failed: %s", exc)

    def _queue_rebuild(self) -> None:
        if self._device_builder is None:
            return
        if self._poll_in_flight:
            self._pending_rebuild = True
            return
        if not self._connected:
            self._pending_rebuild = True
            return
        self._pending_rebuild = False
        self._rebuild_devices()

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
        self._config.save(include_connection=False)

    def _fetch_version(self):
        data = self._api.get_version()
        if data:
            ver = data.get("hercules_version", "")
            modes = ", ".join(data.get("modes", []))
            self._version_label.setText(f"Hercules {ver} | {modes}")
        else:
            self._version_label.clear()

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

        old_devices = self._base_devices
        self._base_devices = []
        self._devices = []
        self._poller.set_devices([])
        self._run_device_hook("cleanup", old_devices, log_message="Device cleanup failed during rebuild: %s")

        self._base_devices = self._device_builder()
        self._devices = self._sort_devices_by_config(self._base_devices)
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

    def _show_preferences(self):
        dialog = PreferencesDialog(self._config, self)
        if dialog.exec() != QDialog.Accepted:
            return

        values = dialog.values()
        endpoint_changed = (
            values["host"] != self._config.host
            or values["port"] != self._config.port
        )
        polling_changed = values["poll_interval"] != self._config.poll_interval
        geometry_changed = any(
            values[key] != getattr(self._config, key)
            for key in ("window_x", "window_y", "window_width", "window_height")
        )
        theme_changed = values["bitmap_theme"] != self._config.bitmap_theme
        room_background = normalize_room_background(values["room_background"])
        room_background_changed = room_background != self._config.room_background
        device_order = parse_device_order(values["device_order"])
        order_changed = device_order != self._config.device_order

        self._config.host = values["host"]
        self._config.port = values["port"]
        self._config.poll_interval = values["poll_interval"]
        self._config.tapes_folder = values["tapes_folder"]
        self._config.bitmap_theme = values["bitmap_theme"]
        self._config.room_background = room_background
        self._config.device_order = device_order
        self._config.window_x = values["window_x"]
        self._config.window_y = values["window_y"]
        self._config.window_width = values["window_width"]
        self._config.window_height = values["window_height"]
        self._config.save()

        if polling_changed:
            self._timer.setInterval(max(1, int(self._config.poll_interval * 1000)))

        if geometry_changed:
            self.resize(self._config.window_width, self._config.window_height)
            if self._config.window_x >= 0 and self._config.window_y >= 0:
                self.move(self._config.window_x, self._config.window_y)

        if theme_changed:
            set_bitmap_theme(self._config.bitmap_theme)
            self._on_bitmap_theme_changed()

        if room_background_changed:
            self._room.set_room_background(self._config.room_background)

        if endpoint_changed:
            self._api.set_base_url(self._config.api_base_url)
            self._connected = self._api.test_connection()
            self._poller.reset_connection_state(self._connected)
            if self._connected:
                self._update_status_connected()
                self._fetch_version()
                self._queue_rebuild()
            else:
                self._update_status_disconnected()
                self._version_label.clear()
                self._pending_rebuild = self._device_builder is not None
        elif theme_changed or room_background_changed or order_changed:
            self._refresh_room_from_current_devices()

    def closeEvent(self, event):
        self._shutting_down = True
        self._timer.stop()
        self._poller.set_devices([])
        self._poll_thread.quit()
        if not self._poll_thread.wait(5000):
            logger.warning("Polling thread did not stop cleanly before shutdown")
        shutdown_progress = ShutdownProgressDialog(self)
        self._run_device_hook(
            "on_app_closing",
            log_message="Device shutdown save failed: %s",
            shutdown_progress=shutdown_progress.update,
        )
        shutdown_progress.close()
        self._run_device_hook("cleanup", log_message="Device cleanup failed during shutdown: %s")
        self._save_geometry()
        super().closeEvent(event)
