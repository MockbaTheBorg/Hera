# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Shared card deck editor and card view widgets for Hera card devices.
Used by Rdr3505Device (card reader) and Pch3525Device (card punch).
"""

import os
from typing import Optional

from PySide6.QtCore import (
    Qt, QPointF, QRectF
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QBrush, QPixmap, QKeyEvent
)
from PySide6.QtWidgets import (
    QWidget, QLabel, QStackedWidget, QSizePolicy, QVBoxLayout
)

from .card_editor import CardEditorWidget
from .card_data import (
    DATA_COLS,
    TOTAL_COLS,
    hollerith_holes,
)

# ── pun1442 card geometry constants (PDF points, 531×243pt card) ─────────────

_CARD_W_PT = 531.0
_CARD_H_PT = 243.0
_HOLE_X0   =  18.42    # Left edge of column 1 hole
_HOLE_Y0   =  54.00    # Top edge of row 0 hole
_HOLE_DX   =   6.21    # Column pitch
_HOLE_DY   =  18.29    # Row pitch
_HOLE_H    =   7.10    # Hole height
_HOLE_W    =   3.00    # Hole width
_HOLE_W_PX =   1.00    # Extra rendered hole width in screen pixels
_TEXT_X_PT =  18.4     # Text overlay x origin
_TEXT_Y_PT =  14.0     # Text overlay y (top, above Y zone)
_CARD_ASPECT = _CARD_W_PT / _CARD_H_PT  # ≈ 2.185

_CARDS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', 'bitmaps', 'cards')
)

_HOLE_COLOR = QColor( 30,  20,  10)   # Near-black punch holes
_TEXT_COLOR = QColor( 30,  20,  10)   # Near-black card text overlay


# ── CardWidget ────────────────────────────────────────────────────────────────

class CardWidget(QWidget):
    """
    Displays one punch card at a time from a deck.
    Shows a real card photograph as background with Hollerith punch holes.
    Up/Down arrow keys navigate through the deck.
    """

    _pixmap_cache: dict[str, Optional[QPixmap]] = {}


    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(400, 200)

        self._lines: list[str] = []
        self._current: int = 0
        self._color: str = 'PAPER'

        self._pos_label = QLabel("", self)
        self._pos_label.setAlignment(Qt.AlignCenter)
        self._pos_label.setStyleSheet(
            "color: #ffffff; font-size: 12px; font-weight: bold; background: transparent;"
        )

    def set_deck(self, lines: list[str], current: int = 0) -> None:
        """Update the displayed deck and navigate to the given card index."""
        self._lines = lines
        self._current = max(0, min(current, max(0, len(lines) - 1)))
        self._update_label()
        self.update()

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    @property
    def current_index(self) -> int:
        return self._current

    def resizeEvent(self, e):
        lh = 20
        self._pos_label.setGeometry(0, self.height() - lh, self.width(), lh)

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() == Qt.Key_Up:
            if self._current > 0:
                self._current -= 1
                self._update_label()
                self.update()
        elif e.key() == Qt.Key_Down:
            if self._current < len(self._lines) - 1:
                self._current += 1
                self._update_label()
                self.update()
        else:
            super().keyPressEvent(e)

    def _update_label(self):
        if self._lines:
            self._pos_label.setText(f"Card {self._current + 1} / {len(self._lines)}")
        else:
            self._pos_label.setText("No cards")

    def _card_draw_rect(self) -> QRectF:
        """Returns the rect for drawing the card, preserving aspect ratio."""
        label_h = self._pos_label.height()
        w = float(self.width())
        h = float(self.height() - label_h)
        if w / h > _CARD_ASPECT:
            card_h = h
            card_w = h * _CARD_ASPECT
        else:
            card_w = w
            card_h = w / _CARD_ASPECT
        x = (w - card_w) / 2.0
        y = (h - card_h) / 2.0
        return QRectF(x, y, card_w, card_h)

    def _get_pixmap(self, color: str) -> Optional[QPixmap]:
        if color not in CardWidget._pixmap_cache:
            fname = f"card_{color.lower()}.png"
            path = os.path.join(_CARDS_DIR, fname)
            pm = QPixmap(path)
            CardWidget._pixmap_cache[color] = None if pm.isNull() else pm
        return CardWidget._pixmap_cache[color]

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Fill widget background
        painter.fillRect(self.rect(), self.palette().window())

        cr = self._card_draw_rect()

        # Draw card background (PNG or fallback)
        pm = self._get_pixmap(self._color)
        if pm is not None:
            painter.drawPixmap(cr.toRect(), pm)
        else:
            painter.fillRect(cr.toRect(), QColor(220, 200, 120))

        if not self._lines or self._current >= len(self._lines):
            return

        line = self._lines[self._current]

        # Draw text overlay (cols 0-71) at top of card
        # Character width = column pitch in pixels; use 1.5× for font height
        char_w_px = _HOLE_DX / _CARD_W_PT * cr.width()
        font_px = max(7, int(char_w_px * 1.5))
        text_font = QFont("Courier New")
        text_font.setStyleHint(QFont.StyleHint.TypeWriter)
        text_font.setPixelSize(font_px)
        painter.setFont(text_font)
        painter.setPen(_TEXT_COLOR)

        # Baseline at _TEXT_Y_PT — just above the Y-zone hole row
        ty = cr.top() + _TEXT_Y_PT / _CARD_H_PT * cr.height()
        # Draw each character at its hole column x position
        text = line[:DATA_COLS]
        for i, ch in enumerate(text):
            cx = cr.left() + (_HOLE_X0 + i * _HOLE_DX) / _CARD_W_PT * cr.width() - 2
            painter.drawText(QPointF(cx, ty), ch)

        # Draw punch holes
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_HOLE_COLOR))
        for col_idx in range(TOTAL_COLS):
            ch = line[col_idx] if col_idx < len(line) else ' '
            for row_idx in hollerith_holes(ch):
                hx = cr.left() + (_HOLE_X0 + col_idx * _HOLE_DX) / _CARD_W_PT * cr.width()
                hy = cr.top()  + (_HOLE_Y0 + row_idx * _HOLE_DY) / _CARD_H_PT * cr.height()
                hw = _HOLE_W / _CARD_W_PT * cr.width() + _HOLE_W_PX
                hh = _HOLE_H / _CARD_H_PT * cr.height()
                painter.drawRect(QRectF(hx - (_HOLE_W_PX / 2.0), hy, hw, hh))

        # Draw sequence number bottom-left of card
        seq = line[DATA_COLS:] if len(line) > DATA_COLS else ''
        seq_font = QFont("Courier New")
        seq_font.setStyleHint(QFont.StyleHint.TypeWriter)
        seq_font.setPixelSize(max(6, font_px - 2))
        painter.setFont(seq_font)
        painter.setPen(_TEXT_COLOR)
        sy = cr.bottom() - 8
        for i, ch in enumerate(seq):
            cx = cr.left() + (_HOLE_X0 + (DATA_COLS + i) * _HOLE_DX) / _CARD_W_PT * cr.width() - 2
            painter.drawText(QPointF(cx, sy), ch)


# ── CardDeckView ──────────────────────────────────────────────────────────────

class CardDeckView(QWidget):
    """
    Container that switches between CardEditorWidget (text form) and
    CardWidget (punch card image view) via a QStackedWidget.
    """

    def __init__(self, initial_mode: str = 'editor',
                 read_only: bool = False,
                 color: str = 'PAPER',
                 lang: str = 'JCL',
                 auto_number: bool = False,
                 parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._editor = CardEditorWidget(read_only=read_only, auto_number=auto_number, parent=self)
        self._card   = CardWidget(parent=self)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._editor)   # index 0 = editor
        self._stack.addWidget(self._card)     # index 1 = card view
        layout.addWidget(self._stack)

        self._mode  = ''
        self.set_color(color)
        self.set_language(lang)
        self.set_mode(initial_mode)

    # ── Deck access ──────────────────────────────────────────────────────────

    @property
    def lines(self) -> list[str]:
        """The current deck (80-char lines). Editor is the source of truth."""
        return self._editor.lines

    @property
    def changed(self) -> bool:
        return self._editor.changed

    @changed.setter
    def changed(self, v: bool):
        self._editor.changed = v

    def set_lines(self, lines: list[str]) -> None:
        self._editor.set_lines(lines)
        if self._mode == 'card':
            self._sync_card_view()

    def append_line(self, line: str) -> None:
        self._editor.append_line(line)
        if self._mode == 'card':
            self._sync_card_view(nav_to_last=True)

    def clear(self) -> None:
        self._editor.clear()
        if self._mode == 'card':
            self._sync_card_view()

    # ── Mode switching ───────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        if mode == 'card':
            self._sync_card_view()
            self._stack.setCurrentIndex(1)
            self._card.setFocus()
        else:
            self._stack.setCurrentIndex(0)
            self._editor.setFocus()
        self._mode = mode

    @property
    def mode(self) -> str:
        return self._mode

    def _sync_card_view(self, nav_to_last: bool = False) -> None:
        lines = self._editor.lines
        idx = (len(lines) - 1) if (nav_to_last and lines) else self._editor.cursor_row
        idx = max(0, min(idx, max(0, len(lines) - 1)))
        self._card.set_deck(lines, idx)

    # ── Setup ─────────────────────────────────────────────────────────────────

    def set_color(self, color: str) -> None:
        self._card.set_color(color)

    def set_language(self, lang: str) -> None:
        self._editor.set_language(lang)

    def set_auto_number(self, auto_number: bool) -> None:
        self._editor.set_auto_number(auto_number)

    @property
    def lang(self) -> str:
        return self._editor.lang
