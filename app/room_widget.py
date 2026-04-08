# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Room area widget for Hera.

Displays a horizontally scrollable strip of device bitmaps with label tabs.
Clicking a device slot selects it and emits device_selected.
"""

import os
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QScrollArea, QHBoxLayout, QVBoxLayout,
    QFrame
)
from PySide6.QtGui import (
    QPainter, QPixmap, QColor, QFont, QPen, QBrush, QPalette
)
from PySide6.QtCore import Qt, Signal, QRect, QSize, QEvent

from .device_base import DeviceBase
from .theme import ROOM_CONTENT_HEIGHT, ROOM_HEIGHT, ROOM_SCROLLBAR_H, room_bg_color
LABEL_HEIGHT = 28                            # Height of the label tab above each device
SELECTED_COLOR = QColor(96, 232, 96)         # Green highlight for selected device
LABEL_DEFAULT_COLOR = QColor(210, 210, 210) # Default label tab background
SLOT_PADDING = 4                             # Horizontal padding between slots
ROOM_BOTTOM_BAND = QColor("#2d2d2d")

from .device_base import bitmaps_dir as _bitmaps_dir


class RoomStrip(QWidget):
    """Shared room background behind the device slots."""

    def __init__(self, background_color: QColor, parent=None):
        super().__init__(parent)
        self._background_color = QColor(background_color)

    def set_background_color(self, color: QColor) -> None:
        self._background_color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._background_color)
        band_top = max(0, self.height() - ROOM_SCROLLBAR_H)
        painter.fillRect(QRect(0, band_top, self.width(), ROOM_SCROLLBAR_H), ROOM_BOTTOM_BAND)
        painter.end()


class DeviceSlot(QWidget):
    """A single device slot in the room: label tab on top, bitmap below."""

    clicked = Signal(int)  # Emits slot index when clicked

    def __init__(self, index: int, device: DeviceBase, background_color: QColor, parent=None):
        super().__init__(parent)
        self.index = index
        self.device = device
        self.selected = False
        self._background_color = QColor(background_color)

        self._pixmap: Optional[QPixmap] = None
        self._load_bitmap()

        # Width matches bitmap width (or minimum 80px)
        w = self._pixmap.width() if self._pixmap else 80
        self.setFixedWidth(w + SLOT_PADDING * 2)
        self.setFixedHeight(ROOM_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

    def _load_bitmap(self):
        path = os.path.join(_bitmaps_dir(), self.device.bitmap_name)
        if os.path.exists(path):
            self._pixmap = QPixmap(path)
        else:
            self._pixmap = None

    def set_selected(self, selected: bool):
        self.selected = selected
        self.update()

    def set_background_color(self, color: QColor) -> None:
        self._background_color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()

        # --- Label tab (top) ---
        label_rect = QRect(0, 0, w, LABEL_HEIGHT)
        tab_color = SELECTED_COLOR if self.selected else LABEL_DEFAULT_COLOR
        painter.fillRect(label_rect, QBrush(tab_color))

        # Raised border around label tab
        painter.setPen(QPen(QColor(180, 180, 180), 1))
        painter.drawRect(label_rect.adjusted(0, 0, -1, -1))

        # Label text
        painter.setPen(QPen(QColor(30, 30, 30)))
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(label_rect.adjusted(4, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft,
                         self.device.label)

        # --- Room background (below label) ---
        body_rect = QRect(0, LABEL_HEIGHT, w, h - LABEL_HEIGHT)
        painter.fillRect(body_rect, QBrush(self._background_color))
        painter.fillRect(
            QRect(0, h - ROOM_SCROLLBAR_H, w, ROOM_SCROLLBAR_H),
            QBrush(ROOM_BOTTOM_BAND),
        )

        # --- Device bitmap (bottom-aligned within body) ---
        if self._pixmap:
            bm_w = self._pixmap.width()
            bm_h = self._pixmap.height()
            # Center horizontally, anchor to content area bottom (not slot bottom)
            x = (w - bm_w) // 2
            y = ROOM_CONTENT_HEIGHT - bm_h
            dest_rect = QRect(x, y, bm_w, bm_h)
            painter.drawPixmap(dest_rect, self._pixmap)

            self.device.draw_room_lights(painter, dest_rect)

            # --- Device overlay (blinkenlights, mini screens) ---
            self.device.draw_room_overlay(painter, dest_rect)

        # Highlight border for selected device
        if self.selected:
            painter.setPen(QPen(SELECTED_COLOR.darker(120), 2))
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)

    def sizeHint(self) -> QSize:
        return QSize(self.width(), ROOM_HEIGHT)


class RoomWidget(QWidget):
    """
    The horizontally scrollable room area.

    Contains a strip of DeviceSlots, one per device.
    Emits device_selected(index) when a slot is clicked.
    """

    device_selected = Signal(int)  # Index into the devices list

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(ROOM_HEIGHT)

        self._devices: list[DeviceBase] = []
        self._slots: list[DeviceSlot] = []
        self._selected_index: int = -1
        self._background_color = room_bg_color()

        # Scroll area fills the widget
        self._scroll = QScrollArea(self)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setWidgetResizable(False)
        self._scroll.setFrameShape(QFrame.NoFrame)

        # Container widget inside scroll area
        self._container = RoomStrip(self._background_color)
        self._container.setFixedHeight(ROOM_HEIGHT)
        self._layout = QHBoxLayout(self._container)
        self._layout.setContentsMargins(4, 0, 4, 0)
        self._layout.setSpacing(2)
        self._layout.addStretch()  # Push slots left

        self._scroll.setWidget(self._container)

        # Room background
        self._apply_viewport_background()

        # Intercept wheel events on the viewport before QScrollArea handles them
        self._scroll.viewport().installEventFilter(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)

    def _apply_viewport_background(self) -> None:
        palette = self._scroll.viewport().palette()
        palette.setColor(QPalette.Window, self._background_color)
        self._scroll.viewport().setPalette(palette)
        self._scroll.viewport().setAutoFillBackground(True)

    def set_room_background(self, color: QColor | str) -> None:
        self._background_color = QColor(color)
        self._apply_viewport_background()
        self._container.set_background_color(self._background_color)
        for slot in self._slots:
            slot.set_background_color(self._background_color)
        self._scroll.viewport().update()
        self._container.update()

    def _clear_slots(self) -> None:
        for slot in self._slots:
            slot.deleteLater()
        self._slots.clear()

    def _reset_layout_tail(self) -> None:
        stretch_item = self._layout.takeAt(self._layout.count() - 1)
        del stretch_item

    def _select_index(self, index: int) -> None:
        self._selected_index = index
        self._slots[index].set_selected(True)
        self.device_selected.emit(index)

    def set_devices(
        self,
        devices: list[DeviceBase],
        *,
        selected_device: Optional[DeviceBase] = None,
        emit_selection: bool = True,
    ):
        """Populate the room with a list of device instances."""
        scroll_value = self._scroll.horizontalScrollBar().value()
        self._clear_slots()
        self._devices = devices
        self._selected_index = -1

        self._reset_layout_tail()

        # Create a slot for each device
        for i, device in enumerate(devices):
            slot = DeviceSlot(i, device, self._background_color, self._container)
            slot.clicked.connect(self._on_slot_clicked)
            self._layout.addWidget(slot)
            self._slots.append(slot)
            device._room_repaint_callback = slot.update

        self._layout.addStretch()
        self._update_container_width()
        self._scroll.horizontalScrollBar().setValue(scroll_value)

        if not self._slots:
            return

        selected_index = -1
        if selected_device is not None:
            try:
                selected_index = self._devices.index(selected_device)
            except ValueError:
                selected_index = -1

        if selected_index < 0:
            selected_index = 0

        if emit_selection:
            self._on_slot_clicked(selected_index)
            return

        self._selected_index = selected_index
        self._slots[selected_index].set_selected(True)

    def _update_container_width(self):
        total = sum(s.width() + 2 for s in self._slots) + 8
        self._container.setFixedWidth(max(total, self._scroll.viewport().width()))

    def _on_slot_clicked(self, index: int):
        if index == self._selected_index:
            return
        # Deselect previous
        if 0 <= self._selected_index < len(self._slots):
            self._slots[self._selected_index].set_selected(False)
            self._devices[self._selected_index].on_deselected()
        self._select_index(index)

    def refresh_slot(self, index: int):
        """Trigger a repaint of a specific slot (e.g. after blinkenlight update)."""
        if 0 <= index < len(self._slots):
            self._slots[index].update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scroll.setGeometry(0, 0, self.width(), ROOM_HEIGHT)
        self._update_container_width()

    def eventFilter(self, obj, event):
        """Intercept wheel events on the scroll area viewport and redirect to horizontal scroll."""
        if obj is self._scroll.viewport() and event.type() == QEvent.Wheel:
            h_bar = self._scroll.horizontalScrollBar()
            delta = event.angleDelta()
            scroll_delta = delta.y() if delta.y() != 0 else delta.x()
            h_bar.setValue(h_bar.value() - scroll_delta)
            return True  # consume — no vertical scroll
        return super().eventFilter(obj, event)

    @property
    def selected_index(self) -> int:
        return self._selected_index
