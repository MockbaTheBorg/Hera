# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Hera CPU device plugin.

Room: cpu.png bitmap with blinkenlights overlay (register bits as 2x2px dots).
Workspace: PSW, GR0-15, CR0-15, AR0-15, MIPS/SIOS rates.
Button column: Three IPL hex dials + IPL button + Start/Stop buttons.
"""
from typing import Optional

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import (
    QPainter, QColor, QBrush, QFont
)
from PySide6.QtCore import Qt, QRect, Signal, QObject

from ..device_base import DeviceBase, ButtonDef, DeviceContext
from ..theme import PANEL_FG
from .cpu_widgets import BUTTON_COLUMN_WIDTH, CpuWorkspace, IplPanel

# Blinkenlight layout — nibble-intensity mode for 64-bit z/Architecture registers.
# cpu_cp.png (151x141) has 2 independent columns × 6 rows of 18 dot-positions each.
# Dots are 2x2px with 1px gap (3px pitch). Rows at y=35,43,51,59,67,75 (8px apart).
# Col1 dot-positions start at x=31; col2 at x=89 (5px gap between columns).
# The 2 leftmost dot-positions per column (x=31,34 / x=89,92) are NEVER drawn —
# 64-bit = 16 nibbles fit exactly in dot-positions 2–17 of each column.
# _blink_data[0..5]  = left column  rows 0–5: GR0, GR1, GR2, GR3, PSW, IA
# _blink_data[6..11] = right column rows 0–5: GR4, GR5, GR6, GR7, 0,   0
BLINK_ROWS         = 8    # rows per column (GR0-7 left, GR8-15 right)
BLINK_DOT_SIZE     = 2    # 2x2px per dot
BLINK_DOT_SPACING  = 3    # 3px pitch (2px dot + 1px gap)
BLINK_ROW_Y_BASE   = 67   # y of row 0 top edge
BLINK_ROW_SPACING  = 8    # y distance between row starts
BLINK_COL1_NIBBLE_X = 36  # x of nibble 0 in left  column
BLINK_COL2_NIBBLE_X = 94  # x of nibble 0 in right column

PSW_ROW_Y   = 141   # y of PSW row: high half in col1, low half in col2
PSW_COL1_X  = 36    # x of nibble 0, left column
PSW_COL2_X  = 94    # x of nibble 0, right column
PSW_COLOR_R = 255   # warm red channel
PSW_COLOR_G = 60
PSW_COLOR_B = 0

class _CpuSignals(QObject):
    workspace_update = Signal(dict, dict)


class CpuDevice(DeviceBase):
    """
    CPU device plugin.
    Handles the virtual CPU device (not address-based).
    """

    device_classes = ["CPU"]
    bitmap_name = "cpu.png"

    def __init__(self, context: Optional[DeviceContext] = None):
        super().__init__(context)
        self._workspace: Optional[CpuWorkspace] = None
        self._ipl_panel: Optional[IplPanel] = None
        self._pending_command: Optional[str] = None
        self._ipl_address: int = 0   # persisted across panel recreations
        self._signals = _CpuSignals()

        # Last fetched data for room overlay
        self._blink_data = [0] * 16  # 8 left col + 8 right col
        self._psw_blink = [0, 0]     # [psw_high_64, psw_low_64]
        self._status_text = "—"
        # State flags for indicator lights
        self._connected = False
        self._cpu_running = False
        self._cpu_wait = False
        self._cpu_active = False   # True only when MIPS > 0
        # Blinkenlights mode: "GR", "CR", or "AR"
        self._blink_mode = "GR"

    def _selected_registers(self, cpu0: dict) -> dict:
        if self._blink_mode == "CR":
            return cpu0.get("control_registers", {})
        if self._blink_mode == "AR":
            return cpu0.get("access_registers", {})
        return cpu0.get("general_registers", {})

    @staticmethod
    def _register_rows(registers: dict, prefix: str) -> list[int]:
        return [int(registers.get(f"{prefix}{i}", "0"), 16) for i in range(16)]

    @staticmethod
    def _wait_bit(psw: str) -> bool:
        if len(psw) < 4:
            return False
        return bool((int(psw[2:4], 16) >> 1) & 1)

    @staticmethod
    def _psw_halves(psw: str) -> list[int]:
        high = int(psw[:16], 16) if len(psw) >= 16 else 0
        low = int(psw[16:32], 16) if len(psw) >= 32 else 0
        return [high, low]

    def _reset_state(self) -> None:
        self._cpu_running = False
        self._cpu_wait = False
        self._cpu_active = False
        self._blink_data = [0] * 16
        self._psw_blink = [0, 0]
        self._status_text = "—"

    @staticmethod
    def _status_text_for(mipsrate: float, running: bool, waiting: bool) -> str:
        state = "RUNNING" if running else "WAIT" if waiting else "STOPPED"
        return f"MIPS {mipsrate:.1f}  {state}"

    def create_workspace(self, parent: QWidget) -> QWidget:
        if self._workspace is None:
            self._workspace = CpuWorkspace(parent)
            self._signals.workspace_update.connect(
                self._workspace.update_cpu, Qt.QueuedConnection
            )
        return self._workspace

    def get_buttons(self) -> list[ButtonDef]:
        # The CPU button column is a complex custom widget; return empty
        # list and have the main window call create_button_widget() separately
        return []

    def button_column_width(self) -> int:
        return BUTTON_COLUMN_WIDTH

    def has_button_column_content(self) -> bool:
        return True

    def create_button_widget(self, parent: QWidget) -> QWidget:
        self._ipl_panel = IplPanel(parent)
        self._ipl_panel.ipl_requested.connect(self._do_ipl)
        self._ipl_panel.command_requested.connect(self._on_command)
        self._ipl_panel.mode_changed.connect(self._on_blink_mode)
        # Restore persisted IPL address
        self._ipl_panel.set_ipl_address(self._ipl_address)
        # Restore persisted blink mode
        for btn in self._ipl_panel._mode_group.buttons():
            btn.setChecked(btn.text() == self._blink_mode)
        # Save address whenever any dial changes
        for dial in self._ipl_panel._dials:
            dial.value_changed.connect(self._save_ipl_address)
        return self._ipl_panel

    def _save_ipl_address(self) -> None:
        if self._ipl_panel is None:
            return
        digits = [d.get_value() for d in self._ipl_panel._dials]
        self._ipl_address = (digits[0] << 8) | (digits[1] << 4) | digits[2]

    def _on_blink_mode(self, mode: str) -> None:
        self._blink_mode = mode

    def _do_ipl(self, addr: str):
        self._pending_command = f"IPL {addr}"

    def _on_command(self, cmd: str):
        self._pending_command = cmd

    def poll(self, api_client) -> None:
        # Send any pending command first
        cmd = self._pending_command
        self._pending_command = None
        if cmd:
            api_client.send_command(cmd)

        # Fetch CPU data
        cpu_result = api_client.get_cpus()
        rates_result = api_client.get_rates() or {}

        self._connected = cpu_result is not None
        if cpu_result is None:
            self._reset_state()
            return

        cpus = cpu_result.get("cpus", [])
        # Use CPU0 for display
        cpu0 = next((c for c in cpus if c.get("cpuid") == "CPU0000"), None)
        if cpu0 is None and cpus:
            cpu0 = cpus[0]
        if cpu0 is None:
            return

        # CPU state flags for indicator lights
        cpu_state = cpu0.get("cpustate", cpu0.get("status", "")).upper()
        mipsrate = rates_result.get("mipsrate", 0)
        self._cpu_running = (cpu_state in ("STARTED",)) or (mipsrate > 0)
        self._cpu_active = mipsrate > 0
        psw_str_raw = cpu0.get("PSW", "")
        self._cpu_wait = self._wait_bit(psw_str_raw)

        # Update blinkenlight data — full 64-bit values, 8 rows per column
        psw_str = cpu0.get("PSW", "0" * 32)
        prefix = self._blink_mode if self._blink_mode != "GR" else "GR"
        self._blink_data = self._register_rows(self._selected_registers(cpu0), prefix)

        # PSW blink data: high 64 bits → left, low 64 bits → right
        self._psw_blink = self._psw_halves(psw_str)

        # Status text for gray panel
        self._status_text = self._status_text_for(mipsrate, self._cpu_running, self._cpu_wait)

        if self._workspace is not None:
            self._signals.workspace_update.emit(cpu0, rates_result)

    def draw_room_overlay(self, painter: QPainter, rect: QRect) -> None:
        """Draw blinkenlights and status indicator lights over the CPU bitmap in the room."""
        ON  = QColor("#FFFBF0")
        OFF = QColor("#000000")

        # Status panel text (gray area x=10-150, y=10-26 in cpu.png coords)
        old_font = painter.font()
        old_pen  = painter.pen()
        painter.setFont(QFont("monospace", 6))
        painter.setPen(QColor(PANEL_FG))
        painter.drawText(QRect(rect.left() + 12, rect.top() + 12, 138, 16),
                         Qt.AlignVCenter | Qt.AlignLeft, self._status_text)
        painter.setFont(old_font)
        painter.setPen(old_pen)

        # Status indicator lights (cpu.png pixel coordinates)
        # Power-on (5×2): lit when connected
        painter.fillRect(rect.left() + 126, rect.top() + 150, 5, 2,
                         ON if self._connected else OFF)
        # SYSTEM (2×2): lit when CPU actively processing (MIPS > 0)
        painter.fillRect(rect.left() + 125, rect.top() + 166, 2, 2,
                         ON if (self._connected and self._cpu_active) else OFF)
        # MANUAL (2×2): lit when connected, stopped, not waiting
        painter.fillRect(rect.left() + 128, rect.top() + 166, 2, 2,
                         ON if (self._connected and not self._cpu_running and not self._cpu_wait) else OFF)
        # WAIT (2×2): lit red when PSW wait bit set
        painter.fillRect(rect.left() + 131, rect.top() + 166, 2, 2,
                         QColor("#FF2020") if self._cpu_wait else OFF)

        col_x = [BLINK_COL1_NIBBLE_X, BLINK_COL2_NIBBLE_X]
        for col in range(2):
            x_base = rect.left() + col_x[col]
            for row in range(BLINK_ROWS):
                val = self._blink_data[col * BLINK_ROWS + row]
                if val == 0:
                    continue
                y = rect.top() + BLINK_ROW_Y_BASE + row * BLINK_ROW_SPACING
                for i in range(16):
                    nibble = (val >> (60 - i * 4)) & 0xF
                    if nibble == 0:
                        continue
                    intensity = int((nibble / 15.0) ** 0.5 * 255)
                    # Incandescent warm white: #FFFBF0 at full intensity
                    color = QColor(intensity, intensity * 251 // 255, intensity * 240 // 255)
                    x = x_base + i * BLINK_DOT_SPACING
                    painter.fillRect(x, y, BLINK_DOT_SIZE, BLINK_DOT_SIZE, QBrush(color))

        # PSW row: high half at col1, low half at col2, both at PSW_ROW_Y
        psw_rows = [(PSW_COL1_X, PSW_ROW_Y, self._psw_blink[0]),
                    (PSW_COL2_X, PSW_ROW_Y, self._psw_blink[1])]
        for x_base_rel, row_y, val in psw_rows:
            if val == 0:
                continue
            x_base = rect.left() + x_base_rel
            y = rect.top() + row_y
            for i in range(16):
                nibble = (val >> (60 - i * 4)) & 0xF
                if nibble == 0:
                    continue
                intensity = int((nibble / 15.0) ** 0.5 * 255)
                color = QColor(intensity * PSW_COLOR_R // 255,
                               intensity * PSW_COLOR_G // 255,
                               intensity * PSW_COLOR_B // 255)
                x = x_base + i * BLINK_DOT_SPACING
                painter.fillRect(x, y, BLINK_DOT_SIZE, BLINK_DOT_SIZE, QBrush(color))
