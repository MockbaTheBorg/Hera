# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""Preferences dialog for editing persisted Hera configuration."""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import (
    CONFIG_FILE,
    Config,
    available_bitmap_themes,
    format_device_order,
    is_valid_room_background,
    normalize_room_background,
)
from .devices.tape_support import validate_folder
from .theme import DIALOG_MIN_WIDTH


class PreferencesDialog(QDialog):
    """Modal editor for Hera's user-configurable settings."""

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._config = config

        self.setWindowTitle("Preferences")
        self.setMinimumWidth(DIALOG_MIN_WIDTH + 80)

        root = QVBoxLayout(self)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_connection_tab(), "Connection")
        tabs.addTab(self._build_appearance_tab(), "Appearance")
        tabs.addTab(self._build_window_tab(), "Window")
        root.addWidget(tabs)

        location = QLabel(f"Config file: {CONFIG_FILE}")
        location.setWordWrap(True)
        root.addWidget(location)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_connection_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        group = QGroupBox("Hercules API", tab)
        form = QFormLayout(group)

        self._host_edit = QLineEdit(self._config.host)
        form.addRow("Host:", self._host_edit)

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(self._config.port)
        form.addRow("Port:", self._port_spin)

        self._poll_interval_spin = QDoubleSpinBox()
        self._poll_interval_spin.setRange(0.05, 60.0)
        self._poll_interval_spin.setDecimals(2)
        self._poll_interval_spin.setSingleStep(0.05)
        self._poll_interval_spin.setValue(self._config.poll_interval)
        self._poll_interval_spin.setSuffix(" s")
        form.addRow("Poll Interval:", self._poll_interval_spin)

        self._tapes_folder_edit = QLineEdit(self._config.tapes_folder)
        self._tapes_folder_edit.setPlaceholderText("Relative path on the Hercules host")
        form.addRow("Tapes Folder:", self._tapes_folder_edit)

        layout.addWidget(group)
        layout.addWidget(QLabel("Changes to host, port, and poll interval are applied immediately."))
        layout.addStretch()
        return tab

    def _build_appearance_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        group = QGroupBox("Room Display", tab)
        form = QFormLayout(group)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(available_bitmap_themes())
        self._theme_combo.setCurrentText(self._config.bitmap_theme)
        form.addRow("Bitmap Theme:", self._theme_combo)

        color_row = QWidget(group)
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(6)

        self._room_background_edit = QLineEdit(self._config.room_background)
        self._room_background_edit.setPlaceholderText("#9da89b")
        self._room_background_edit.textChanged.connect(self._set_room_background_preview)
        color_layout.addWidget(self._room_background_edit)

        self._room_background_button = QPushButton("Choose...")
        self._room_background_button.clicked.connect(self._choose_room_background)
        color_layout.addWidget(self._room_background_button)

        self._room_background_preview = QLabel()
        self._room_background_preview.setFixedWidth(36)
        self._room_background_preview.setMinimumHeight(24)
        color_layout.addWidget(self._room_background_preview)
        form.addRow("Room Background:", color_row)
        self._set_room_background_preview(self._config.room_background)

        self._device_order_edit = QLineEdit(format_device_order(self._config.device_order))
        self._device_order_edit.setPlaceholderText("Example: CONSOLE,CPU,DASD,TAPE,DSP,PRT")
        form.addRow("Device Order:", self._device_order_edit)

        layout.addWidget(group)
        order_help = QLabel(
            "Device order is a comma-separated list of Hercules device classes. "
            "Any class not listed stays after the named classes."
        )
        order_help.setWordWrap(True)
        layout.addWidget(order_help)
        layout.addStretch()
        return tab

    def _set_room_background_preview(self, color: str) -> None:
        preview_color = normalize_room_background(color)
        self._room_background_preview.setStyleSheet(
            f"background-color: {preview_color}; border: 1px solid #444444;"
        )

    def _choose_room_background(self) -> None:
        current = QColor(normalize_room_background(self._room_background_edit.text()))
        selected = QColorDialog.getColor(current, self, "Select Room Background")
        if not selected.isValid():
            return
        self._room_background_edit.setText(selected.name().lower())

    def _build_window_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        group = QGroupBox("Main Window", tab)
        form = QFormLayout(group)

        self._window_x_spin = QSpinBox()
        self._window_x_spin.setRange(-1, 32767)
        self._window_x_spin.setValue(self._config.window_x)
        form.addRow("X Position:", self._window_x_spin)

        self._window_y_spin = QSpinBox()
        self._window_y_spin.setRange(-1, 32767)
        self._window_y_spin.setValue(self._config.window_y)
        form.addRow("Y Position:", self._window_y_spin)

        self._window_width_spin = QSpinBox()
        self._window_width_spin.setRange(640, 32767)
        self._window_width_spin.setValue(self._config.window_width)
        form.addRow("Width:", self._window_width_spin)

        self._window_height_spin = QSpinBox()
        self._window_height_spin.setRange(480, 32767)
        self._window_height_spin.setValue(self._config.window_height)
        form.addRow("Height:", self._window_height_spin)

        layout.addWidget(group)
        hint = QLabel(
            "If X or Y is -1, Hera keeps the current position when applying the change. "
            "The live window position is still saved on exit."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        return tab

    def values(self) -> dict:
        return {
            "host": self._host_edit.text().strip(),
            "port": self._port_spin.value(),
            "poll_interval": self._poll_interval_spin.value(),
            "tapes_folder": validate_folder(self._tapes_folder_edit.text()),
            "bitmap_theme": self._theme_combo.currentText().strip(),
            "room_background": self._room_background_edit.text().strip(),
            "device_order": self._device_order_edit.text().strip(),
            "window_x": self._window_x_spin.value(),
            "window_y": self._window_y_spin.value(),
            "window_width": self._window_width_spin.value(),
            "window_height": self._window_height_spin.value(),
        }

    def _validate_and_accept(self) -> None:
        values = self.values()
        if not values["host"]:
            QMessageBox.warning(self, "Validation", "Host is required.")
            return
        if values["room_background"] and not is_valid_room_background(values["room_background"]):
            QMessageBox.warning(self, "Validation", "Room background must be a hex color like #9da89b.")
            return

        self._host_edit.setText(values["host"])
        self._tapes_folder_edit.setText(values["tapes_folder"])
        self._room_background_edit.setText(normalize_room_background(values["room_background"]))
        self.accept()