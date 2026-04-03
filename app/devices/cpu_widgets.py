# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Widget classes for the CPU device.
"""

import math
from typing import Optional

from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QColor, QPen, QBrush, QFont, QPalette, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame,
)

from ..theme import PANEL_BG, PANEL_FG, BUTTON_HEIGHT, button_style

BUTTON_COLUMN_WIDTH = 280  # wider than default to fit three IPL dials side-by-side


class IplDial(QWidget):
    """Single rotary hex dial widget. Displays 16 hex chars around a circle."""

    value_changed = Signal(int)  # 0-15

    def __init__(self, digit_index: int, parent=None):
        super().__init__(parent)
        self.digit_index = digit_index   # 0=LSB, 1=mid, 2=MSB
        self._value = 0                  # 0-15
        self._capture_angle: Optional[float] = None
        self._capture_value: int = 0
        self.setFixedSize(80, 80)
        self.setCursor(Qt.PointingHandCursor)

    def set_value(self, v: int):
        self._value = v & 0xF
        self.update()

    def get_value(self) -> int:
        return self._value

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        cx = self.width() // 2
        cy = self.height() // 2
        r = min(cx, cy) - 4

        painter.setBrush(QBrush(QColor(200, 200, 200)))
        painter.setPen(QPen(QColor(100, 100, 100), 2))
        painter.drawEllipse(QPoint(cx, cy), r, r)

        painter.setBrush(QBrush(QColor(150, 150, 150)))
        painter.drawEllipse(QPoint(cx, cy), 8, 8)

        font = QFont()
        font.setPointSize(7)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(Qt.black))

        for i in range(16):
            angle = (2 * math.pi * i / 16) - math.pi / 2
            tx = cx + (r - 10) * math.cos(angle)
            ty = cy + (r - 10) * math.sin(angle)
            char_val = (self._value + i) & 0xF
            ch = hex(char_val)[2:].upper()
            painter.setPen(QPen(QColor(0, 100, 200) if i == 0 else QColor(60, 60, 60)))
            painter.drawText(QRect(int(tx) - 6, int(ty) - 7, 12, 14), Qt.AlignCenter, ch)

        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._capture_angle = self._point_angle(event.position())
            self._capture_value = self._value
            self.grabMouse()

    def mouseMoveEvent(self, event):
        if self._capture_angle is None:
            return
        angle = self._point_angle(event.position())
        delta_angle = self._capture_angle - angle
        delta_steps = int(round(delta_angle * 8 / math.pi)) & 0xF
        new_val = (self._capture_value + delta_steps) & 0xF
        if new_val != self._value:
            self._value = new_val
            self.value_changed.emit(self._value)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._capture_angle = None
            self.releaseMouse()

    def _point_angle(self, pos) -> float:
        cx = self.width() / 2
        cy = self.height() / 2
        dx = pos.x() - cx
        dy = pos.y() - cy
        if abs(dx) < 0.01 and abs(dy) < 0.01:
            return 0.0
        return math.atan2(dy, dx)


class IplPanel(QWidget):
    """Three hex dials + IPL address display + operator buttons."""

    ipl_requested = Signal(str)
    command_requested = Signal(str)
    mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(PANEL_BG))
        self.setPalette(pal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(6)

        from PySide6.QtWidgets import QButtonGroup, QMessageBox
        btn_style = button_style(
            bg="#606060", fg="#E8E8E8", border_color="#A0A0A0",
            checked_bg="#2060A0", checked_border="#60A0E0", font_size=11,
        )
        mode_row = QHBoxLayout()
        mode_row.setSpacing(2)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for label in ("GR", "CR", "AR"):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(BUTTON_HEIGHT)
            btn.setStyleSheet(btn_style)
            if label == "GR":
                btn.setChecked(True)
            self._mode_group.addButton(btn)
            mode_row.addWidget(btn)
        self._mode_group.buttonClicked.connect(lambda b: self.mode_changed.emit(b.text()))
        layout.addLayout(mode_row)

        self._addr_label = QLabel("IPL: 000")
        self._addr_label.setAlignment(Qt.AlignCenter)
        self._addr_label.setStyleSheet(
            "font-family: monospace; font-size: 13px; font-weight: bold; color: #E8E8E8;"
        )
        layout.addWidget(self._addr_label)

        dial_row = QHBoxLayout()
        dial_row.setSpacing(2)
        self._dials = []
        for i in range(2, -1, -1):
            dial = IplDial(i)
            dial.value_changed.connect(self._update_address)
            self._dials.append(dial)
            dial_row.addWidget(dial)
        layout.addLayout(dial_row)

        ipl_btn = QPushButton("IPL")
        ipl_btn.setFixedHeight(BUTTON_HEIGHT)
        ipl_btn.setStyleSheet(button_style(bold=True, font_size=12))
        ipl_btn.clicked.connect(self._do_ipl)
        layout.addWidget(ipl_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        op_grid = QGridLayout()
        op_grid.setSpacing(4)

        def _op_btn(label, bg, cmd=None, confirm=False):
            b = QPushButton(label)
            b.setFixedHeight(BUTTON_HEIGHT)
            b.setStyleSheet(button_style(bg=bg, fg="#E8E8E8", font_size=11))
            if cmd and not confirm:
                b.clicked.connect(lambda: self.command_requested.emit(cmd))
            elif cmd and confirm:
                def _confirmed():
                    r = QMessageBox.question(
                        None, "Quit", "Are you sure you want to power off?",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                    )
                    if r == QMessageBox.Yes:
                        self.command_requested.emit(cmd)
                b.clicked.connect(_confirmed)
            return b

        buttons = [
            ("Store Status", "#205080", "store", False),
            ("Restart", "#205080", "restart", False),
            ("Start", "#206020", "startall", False),
            ("Stop", "#802020", "stopall", False),
            ("Power On", "#909090", None, False),
            ("Power Off", "#802020", "quit", True),
            ("Interrupt", "#802020", "ext", False),
            ("Load", "#205080", None, False),
        ]
        for idx, (label, bg, cmd, confirm) in enumerate(buttons):
            op_grid.addWidget(_op_btn(label, bg, cmd, confirm), idx // 2, idx % 2)

        layout.addLayout(op_grid)
        layout.addStretch()

    def _dial_address(self) -> str:
        return "".join(hex(d.get_value())[2:].upper() for d in self._dials)

    def _update_address(self):
        self._addr_label.setText(f"IPL: {self._dial_address()}")

    def _do_ipl(self):
        self.ipl_requested.emit(self._dial_address())

    def set_ipl_address(self, addr: int):
        digits = [(addr >> 8) & 0xF, (addr >> 4) & 0xF, addr & 0xF]
        for i, d in enumerate(digits):
            self._dials[i].set_value(d)
        self._update_address()


class CpuWorkspace(QWidget):
    """Displays PSW, GR/CR/AR registers and MIPS/SIOS rates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(PANEL_BG))
        self.setPalette(pal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        lbl_style = f"font-family: 'Courier New', monospace; font-size: 13px; font-weight: bold; color: {PANEL_FG};"
        mono_style = f"font-family: 'Courier New', monospace; font-size: 13px; color: {PANEL_FG};"

        psw_row = QHBoxLayout()
        psw_lbl = QLabel("PSW:")
        psw_lbl.setStyleSheet(lbl_style)
        psw_row.addWidget(psw_lbl)
        self._psw = QLabel("0000000000000000 0000000000000000")
        self._psw.setStyleSheet(mono_style)
        psw_row.addWidget(self._psw)
        psw_row.addStretch()
        layout.addLayout(psw_row)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); layout.addWidget(sep)

        layout.addWidget(self._section_label("General Registers"))
        self._gr_grid = QGridLayout()
        self._gr_labels = {}
        for i in range(16):
            lbl = QLabel(f"GR{i:2d}:")
            lbl.setStyleSheet(lbl_style)
            val = QLabel("0000000000000000")
            val.setStyleSheet(mono_style)
            self._gr_labels[f"GR{i}"] = val
            self._gr_grid.addWidget(lbl, i // 4, (i % 4) * 2)
            self._gr_grid.addWidget(val, i // 4, (i % 4) * 2 + 1)
        self._gr_grid.setColumnStretch(8, 1)
        layout.addLayout(self._gr_grid)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); layout.addWidget(sep2)

        layout.addWidget(self._section_label("Control Registers"))
        self._cr_grid = QGridLayout()
        self._cr_labels = {}
        for i in range(16):
            lbl = QLabel(f"CR{i:2d}:")
            lbl.setStyleSheet(lbl_style)
            val = QLabel("0000000000000000")
            val.setStyleSheet(mono_style)
            self._cr_labels[f"CR{i}"] = val
            self._cr_grid.addWidget(lbl, i // 4, (i % 4) * 2)
            self._cr_grid.addWidget(val, i // 4, (i % 4) * 2 + 1)
        self._cr_grid.setColumnStretch(8, 1)
        layout.addLayout(self._cr_grid)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.HLine); layout.addWidget(sep3)

        layout.addWidget(self._section_label("Access Registers"))
        self._ar_grid = QGridLayout()
        self._ar_labels = {}
        for i in range(16):
            lbl = QLabel(f"AR{i:2d}:")
            lbl.setStyleSheet(lbl_style)
            val = QLabel("00000000")
            val.setStyleSheet(mono_style)
            self._ar_labels[f"AR{i}"] = val
            self._ar_grid.addWidget(lbl, i // 4, (i % 4) * 2)
            self._ar_grid.addWidget(val, i // 4, (i % 4) * 2 + 1)
        self._ar_grid.setColumnStretch(8, 1)
        layout.addLayout(self._ar_grid)

        sep4 = QFrame(); sep4.setFrameShape(QFrame.HLine); layout.addWidget(sep4)

        rates_row = QHBoxLayout()
        self._mips = QLabel("MIPS: 0.00")
        self._sios = QLabel("SIOS: 0")
        self._mips.setStyleSheet(mono_style)
        self._sios.setStyleSheet(mono_style)
        rates_row.addWidget(self._mips)
        rates_row.addWidget(self._sios)
        rates_row.addStretch()
        layout.addLayout(rates_row)

        layout.addStretch()

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-weight: bold; font-size: 10px; color: {PANEL_FG};")
        return lbl

    def update_cpu(self, cpu_data: dict, rates: dict):
        psw = cpu_data.get("PSW", "")
        self._psw.setText(psw[:16] + " " + psw[16:] if len(psw) >= 16 else psw)

        gr = cpu_data.get("general_registers", {})
        for key, lbl in self._gr_labels.items():
            lbl.setText(gr.get(key, "0000000000000000"))

        cr = cpu_data.get("control_registers", {})
        for key, lbl in self._cr_labels.items():
            lbl.setText(cr.get(key, "0000000000000000"))

        ar = cpu_data.get("access_registers", {})
        for key, lbl in self._ar_labels.items():
            lbl.setText(ar.get(key, "00000000"))

        self._mips.setText(f"MIPS: {rates.get('mipsrate', 0):.2f}")
        self._sios.setText(f"SIOS: {rates.get('siosrate', 0)}")
