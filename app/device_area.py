# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Device area widget for Hera.

Horizontal split: workspace (left, stretches) + button column (right, 120px fixed).
Content swaps when a different device is selected.
"""

from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QFrame,
    QPushButton, QSizePolicy, QLabel, QScrollArea
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

from .device_base import DeviceBase, ButtonDef
from .theme import BUTTON_HEIGHT, BUTTON_COLUMN_WIDTH, BUTTON_SPACING, DEVICE_AREA_BG, button_style


class ButtonColumn(QWidget):
    """Fixed-width column on the right side of the device area."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(BUTTON_COLUMN_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        # Outer layout holds the inner scroll area
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self._scroll)

        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(BUTTON_SPACING)
        self._layout.addStretch()
        self._scroll.setWidget(self._inner)

        self._widgets: list[QWidget] = []

    def _clear_widgets(self) -> None:
        for widget in self._widgets:
            self._layout.removeWidget(widget)
            widget.deleteLater()
        self._widgets.clear()

    def _take_trailing_stretch(self) -> None:
        self._layout.takeAt(self._layout.count() - 1)

    def _styled_button(self, btn_def: ButtonDef, *, font_size: int | None = None) -> QPushButton:
        button = QPushButton(btn_def.label)
        button.setFixedHeight(BUTTON_HEIGHT)
        button.setEnabled(btn_def.enabled)
        button.setStyleSheet(button_style(font_size=font_size) if font_size else button_style())
        if btn_def.tooltip:
            button.setToolTip(btn_def.tooltip)
        if btn_def.callback is not None:
            button.clicked.connect(btn_def.callback)
        if btn_def.on_created:
            btn_def.on_created(button)
        return button

    def _label_widget(self, btn_def: ButtonDef) -> QLabel:
        label = QLabel(btn_def.label)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            "color: #666666; font-size: 11px; font-weight: bold; "
            "padding-top: 6px; padding-bottom: 2px;"
        )
        return label

    def _populate_single_column(self, buttons: list[ButtonDef]) -> None:
        for btn_def in buttons:
            widget = self._label_widget(btn_def) if btn_def.is_label else self._styled_button(btn_def)
            self._layout.addWidget(widget)
            self._widgets.append(widget)

    def _populate_multi_column(self, buttons: list[ButtonDef], cols: int) -> None:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(BUTTON_SPACING)
        row = 0
        col = 0

        for btn_def in buttons:
            if btn_def.is_label:
                if col != 0:
                    row += 1
                    col = 0
                grid.addWidget(self._label_widget(btn_def), row, 0, 1, cols)
                row += 1
                continue

            if btn_def.full_width:
                if col != 0:
                    row += 1
                    col = 0
                grid.addWidget(self._styled_button(btn_def, font_size=14), row, 0, 1, cols)
                row += 1
                continue

            grid.addWidget(self._styled_button(btn_def, font_size=14), row, col)
            col += 1
            if col >= cols:
                row += 1
                col = 0

        self._layout.addWidget(container)
        self._widgets.append(container)

    def set_buttons(self, buttons: list[ButtonDef], cols: int = 1):
        """Replace button column content with new button definitions."""
        self._clear_widgets()
        self._take_trailing_stretch()
        if cols > 1:
            self._populate_multi_column(buttons, cols)
        else:
            self._populate_single_column(buttons)
        self._layout.addStretch()

    def add_widget(self, widget: QWidget):
        """Add an arbitrary widget to the button column (above the stretch)."""
        self._layout.takeAt(self._layout.count() - 1)
        self._layout.addWidget(widget)
        self._widgets.append(widget)
        self._layout.addStretch()

    def clear(self):
        self.set_buttons([])


class Workspace(QWidget):
    """Left side of the device area — holds the current device's workspace widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._current: Optional[QWidget] = None

    def set_content(self, widget: QWidget):
        """Swap in a new workspace widget."""
        if self._current is not None:
            self._layout.removeWidget(self._current)
            self._current.setParent(None)
        self._current = widget
        if widget is not None:
            self._layout.addWidget(widget)


class DeviceArea(QWidget):
    """
    The bottom half of the main window.
    Left: device workspace (stretches).
    Right: button column (fixed 120px).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(DEVICE_AREA_BG))
        self.setPalette(palette)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._workspace = Workspace()
        self._buttons = ButtonColumn()

        # Separator line between workspace and button column
        self._separator = QFrame()
        self._separator.setFrameShape(QFrame.VLine)
        self._separator.setFrameShadow(QFrame.Sunken)

        layout.addWidget(self._workspace, stretch=1)
        layout.addWidget(self._separator)
        layout.addWidget(self._buttons)

        self._current_device: Optional[DeviceBase] = None
        self._show_placeholder()

    def _show_placeholder(self):
        placeholder = QLabel("No device selected")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: #888888; font-size: 13px;")
        self._workspace.set_content(placeholder)
        self._buttons.clear()

    def set_visible(self, visible: bool):
        """Show or hide the separator and button column together."""
        self._separator.setVisible(visible)
        self._buttons.setVisible(visible)

    def show_placeholder(self):
        """Reset the device area to its placeholder state."""
        self._show_placeholder()
        self.set_visible(False)

    def select_device(self, device: DeviceBase):
        """Update workspace and buttons for the newly selected device."""
        self._current_device = device
        self._buttons.setFixedWidth(device.button_column_width())
        workspace_widget = device.create_workspace(self._workspace)
        self._workspace.set_content(workspace_widget)
        self._buttons.set_buttons(device.get_buttons(), cols=device.button_columns())

    def get_button_column(self) -> ButtonColumn:
        """Expose button column for devices that need to add custom widgets."""
        return self._buttons
