# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Hera unified line-printer device plugin.

Handles devclass="PRT" (IBM 1403 line printer and IBM 3215 Console Printer).

Mode detection:
  - devport == 3215 → 3215 mode
    (dotmatrix font, normal paper orientation, command input, 3215.png bitmap)
  - Otherwise → 1403 mode
    (impact font, reversed paper orientation, no command input, 1403.png bitmap)

Output arrives in real time via a Hercules sockdevice TCP connection.
In 3215 mode, operator commands are dispatched via the REST API syslog endpoint.
"""

import logging
import os
from collections import deque
from datetime import datetime
from typing import Callable, Optional

import shiboken6
from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtGui import QColor, QFontDatabase, QPainter
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ..device_base import DeviceBase, ButtonDef, DeviceContext
from ..socket_reader import SocketLineReader as SocketReader
from ..theme import DIALOG_MIN_WIDTH, button_style
from ..widgets.mini_screen import MiniScreenOverlay
from ..widgets.printer_workspace import PrinterWorkspace

logger = logging.getLogger(__name__)

# ── Mini-print per-device configuration ──────────────────────────────────────
# Tuple: (x, base_y, w, max_h, max_lines, rotation)
#   x, base_y  – bitmap coords of the "base" anchor (where paper exits the device)
#   w          – area width in bitmap pixels
#   max_h      – max area height in bitmap pixels
#   max_lines  – lines to retain from the print buffer before scrolling
#   rotation   – 0:   area grows UPWARD   from base_y (3215 style, no rotation)
#                180: area grows DOWNWARD from base_y (1403 style, text flipped)
#
# Mini-print font height is fixed per device via MINI_FONT_PX_3215 and
# MINI_FONT_PX_1403 rather than being derived from max_h/max_lines.
#
# 3215: paper exits at the BOTTOM of the mini-area.
#       base_y = y + max_h = 1 + 43 = 44; area grows upward from there.
# 1403: paper exits at the TOP of the mini-area (printer head at y=90).
#       base_y = 90; area grows downward to the paper-collection box (~y=176).

MINI_FONT_PX_3215 = 1
MINI_FONT_PX_1403 = 1
WORKSPACE_SIDE_MARGIN_CHARS = 4
MINI_SIDE_MARGIN_CHARS = 2

_MINI_3215 = (27, 44,  81, 43, 66, 0)
_MINI_1403 = (55, 90, 112, 86, 86, 180)

# Standard green-bar colors for both mini-screen and workspace
BAR_EVEN   = QColor(255, 255, 255)   # white (uncolored bands)
BAR_ODD    = QColor(221, 255, 221)   # #DDFFDD default green
TEXT_COLOR = QColor(0, 0, 0)

PAGE_LENGTH = 66  # standard IBM fan-fold page (11" at 6 lpi)
PAGE_WIDTH  = 132
DEFAULT_3215_LINE_DELAY_MS = 10
DEFAULT_3215_BLANK_LINE_DELAY_MS = 1
DEFAULT_1403_LINE_DELAY_MS = 30
DEFAULT_1403_BLANK_LINE_DELAY_MS = 3

# ── Paper color palettes ──────────────────────────────────────────────────────
# Each entry: (dark_QColor, light_QColor) matching prt1403 reference RGB values.
# dark  → band border / text color
# light → colored band fill (becomes bar_odd in the workspace)
PAPER_COLORS = {
    "GREEN":  (QColor( 99, 182,  99), QColor(219, 250, 219)),
    "BLUE":   (QColor( 65, 182, 255), QColor(214, 239, 255)),
    "ORANGE": (QColor(219, 182,  99), QColor(255, 221, 146)),
    "GRAY":   (QColor(200, 200, 200), QColor(230, 230, 230)),
    "WHITE":  (QColor(255, 255, 255), QColor(255, 255, 255)),
}

# ── Font loader ───────────────────────────────────────────────────────────────

def _load_font(filename: str) -> str:
    """Register a font from the fonts/ directory.  Returns the family name or ""."""
    font_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "fonts", filename)
    )
    if not os.path.exists(font_path):
        logger.warning("Font not found: %s", font_path)
        return ""
    font_id = QFontDatabase.addApplicationFont(font_path)
    if font_id == -1:
        logger.warning("Failed to load font: %s", font_path)
        return ""
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        logger.warning("Font %s loaded but has no families", filename)
        return ""
    logger.debug("Loaded font %s → family %s", filename, families[0])
    return families[0]


# ── Device plugin ─────────────────────────────────────────────────────────────

class Prt1403Device(DeviceBase):
    """
    Unified IBM line-printer device plugin.
    Handles devclass="PRT" (1403 and 3215).
    """

    device_classes = ["PRT"]

    def __init__(
        self,
        context: Optional[DeviceContext] = None,
    ):
        super().__init__(context)

        # ── Mode detection ────────────────────────────────────────────
        self._is_3215: bool = (self.devport == 3215)
        port = self.devport if self.devport else 3270  # fallback for socket connection
        self._port = port
        self._host = self.host or "127.0.0.1"
        self._devnum = self.devnum
        self._config = self.config

        if self._is_3215:
            self.bitmap_name = "3215.png"
            self._font_filename = "dotmatrix.ttf"
            self._font_family = _load_font(self._font_filename)
            bx, by, bw, bmax_h, bmax_lines, brot = _MINI_3215
            self._mini_font_px = MINI_FONT_PX_3215
        else:
            self.bitmap_name = "1403.png"
            self._font_filename = "impact.ttf"
            self._font_family = _load_font(self._font_filename)
            bx, by, bw, bmax_h, bmax_lines, brot = _MINI_1403
            self._mini_font_px = MINI_FONT_PX_1403

        # Per-device mini-print parameters
        self._mini_max_lines: int = bmax_lines
        self._mini_rotation: int = brot

        # ── Paper color ───────────────────────────────────────────────
        _default_color = "WHITE" if self._is_3215 else "GREEN"
        self._color_name: str = _default_color
        if self._config is not None:
            saved = self._config.get_setting("devices", f"printer_color_{self._devnum}", _default_color)
            if saved in PAPER_COLORS:
                self._color_name = saved

        bar_even, bar_odd = self._current_colors()

        # ── Mini-screen (green-bar mode) ──────────────────────────────
        # The logic is identical for both devices; the only difference is
        # rotation and which edge is the fixed "base":
        #   rotation=0   → base is at the BOTTOM (y = base_y - max_h), grows up
        #   rotation=180 → base is at the TOP    (y = base_y),         grows down
        if brot == 0:
            mso_y = by - bmax_h      # top of area in bitmap coords
            top_anchored = False     # fixed bottom, grows upward
        else:
            mso_y = by               # top of area == base (printer head)
            top_anchored = True      # fixed top, grows downward

        self._mini_screen = MiniScreenOverlay(
            bx, mso_y, bw, bmax_h,
            max_lines=bmax_lines,
            max_cols=PAGE_WIDTH,
            bar_even=bar_even,
            bar_odd=bar_odd,
            text_color=TEXT_COLOR,
            top_anchored=top_anchored,
            page_header_lines=6,
            lines_per_band=3,
            page_length=PAGE_LENGTH,
            fixed_line_px=self._mini_font_px,
            side_margin_chars=MINI_SIDE_MARGIN_CHARS,
        )
        self._mini_lines: list[str] = []

        # ── Socket reader ─────────────────────────────────────────────
        self._reader = SocketReader(
            self._host,
            port,
            thread_name=f"SocketReader:{port}",
            logger=logger,
            recv_timeout=1.0,
        )
        self._reader.line_received.connect(self._on_socket_line)
        self._reader.start()

        # ── State ─────────────────────────────────────────────────────
        self._all_lines: list[str] = []
        self._queued_lines: deque[str] = deque()
        self._saved: bool = True
        self._workspace: Optional[PrinterWorkspace] = None
        self._pending_command: Optional[str] = None
        self._api_client = self.api_client
        self._btn_connect = None
        self._btn_disconnect = None
        self._disconnect_dlg = None
        self.room_light_origin = None if self._is_3215 else (7, 15)
        self._reader.connected_changed.connect(self._on_connection_changed, Qt.QueuedConnection)
        self._line_delay_ms = self._load_delay_ms(
            key=f"printer_line_delay_ms_{self._devnum}",
            default=self._default_line_delay_ms(),
            label="printer line delay",
        )
        self._blank_line_delay_ms = self._load_delay_ms(
            key=f"printer_blank_line_delay_ms_{self._devnum}",
            default=self._default_blank_line_delay_ms(),
            label="printer blank-line delay",
        )
        self._print_timer = QTimer()
        self._print_timer.setSingleShot(True)
        self._print_timer.timeout.connect(self._drain_print_queue)

    def _set_socket_button(self, button, enabled: bool):
        if button is not None and shiboken6.isValid(button):
            button.setEnabled(enabled)
            return button
        return None

    def _sync_connection_buttons(self, connected: bool) -> None:
        self._btn_connect = self._set_socket_button(self._btn_connect, not connected)
        self._btn_disconnect = self._set_socket_button(self._btn_disconnect, connected)

    def _set_paper_colors(self, color_name: str) -> None:
        self._color_name = color_name
        bar_even, bar_odd = self._current_colors()
        self._mini_screen._bar_even = bar_even
        self._mini_screen._bar_odd = bar_odd
        if self._workspace is not None:
            self._workspace._bar_even = bar_even
            self._workspace._bar_odd = bar_odd
            self._workspace._color_name = color_name
            self._workspace._paper._bar_even = bar_even
            self._workspace._paper._bar_odd = bar_odd
            self._workspace._paper.set_lines(self._all_lines[:])
        self.request_room_repaint()
        if self._config is not None:
            self._config.set_setting("devices", f"printer_color_{self._devnum}", color_name)

    @staticmethod
    def _contrast_color(r: int, g: int, b: int) -> str:
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        return "#000000" if lum > 128 else "#ffffff"

    def _paper_color_button(self, name: str, selected: dict, dlg: QDialog) -> QPushButton:
        _, light = PAPER_COLORS[name]
        btn = QPushButton(name)
        r, g, b = light.red(), light.green(), light.blue()
        btn.setFixedSize(80, 48)
        btn.setStyleSheet(button_style(
            bg=f"rgb({r},{g},{b})",
            fg=self._contrast_color(r, g, b),
            border_color="#888888",
            border_width=2,
            font_size=11,
            bold=True,
            extra="QPushButton:hover { border-color: #333333; }",
        ))
        btn.clicked.connect(lambda checked=False, n=name: (selected.__setitem__("name", n), dlg.accept()))
        return btn

    # ------------------------------------------------------------------
    # DeviceBase interface
    # ------------------------------------------------------------------

    def create_workspace(self, parent: QWidget) -> QWidget:
        if self._workspace is None:
            bar_even, bar_odd = self._current_colors()
            self._workspace = PrinterWorkspace(
                parent,
                font_family=self._font_family,
                bar_even=bar_even,
                bar_odd=bar_odd,
                page_length=PAGE_LENGTH,
                has_command_input=self._is_3215,
                color_name=self._color_name,
                side_margin_chars=WORKSPACE_SIDE_MARGIN_CHARS,
            )  # GreenBarPaper defaults: lines_per_band=3, page_header_lines=6
            if self._is_3215:
                self._workspace.send_command.connect(self._on_send_command)
            # Replay full history into the workspace
            if self._all_lines:
                self._workspace._update_display.emit(self._all_lines[:], True)
        return self._workspace

    def get_buttons(self) -> list[ButtonDef]:
        return [
            ButtonDef(label="Setup",   callback=self._do_setup),
            ButtonDef(label="Save",    callback=self._do_save),
            ButtonDef(label="Discard", callback=self._do_discard),
            ButtonDef(label="Test",    callback=self._do_test),
            ButtonDef(label="Socket", is_label=True),
            ButtonDef(
                label="Connect",
                callback=self._do_connect,
                on_created=self._on_connect_button_created,
            ),
            ButtonDef(
                label="Disconnect",
                callback=self._do_disconnect,
                on_created=self._on_disconnect_button_created,
            ),
        ]

    def draw_room_overlay(self, painter: QPainter, rect) -> None:
        self._mini_screen.render(
            painter, rect, self._mini_lines,
            line_count=len(self._all_lines),
            rotate_180=(self._mini_rotation == 180),
        )

    def poll(self, api_client) -> None:
        """Dispatch pending command (3215 mode only); socket handles data input."""
        if not self._is_3215:
            return
        cmd = self._pending_command
        self._pending_command = None
        if cmd and api_client is not None:
            api_client.syslog_feed.send_command(cmd)

    def on_selected(self, api_client=None) -> None:
        if self._workspace is not None:
            self._workspace.focus_input()

    def cleanup(self) -> None:
        self._print_timer.stop()
        self._reader.stop()

    def on_app_closing(
        self,
        shutdown_progress: Callable[[str, int, int], None] | None = None,
    ) -> None:
        """Persist buffered printer output to a deterministic PDF on shutdown."""
        if self._config is not None:
            raw = self._config.get_setting("shutdown", "autosave_printer_pdfs", "1").strip().lower()
            if raw not in {"1", "true", "yes", "on"}:
                return
        lines = self._all_lines + list(self._queued_lines)
        if not lines:
            return
        prefix = "CON" if self._is_3215 else "PRT"
        path = os.path.join(os.getcwd(), f"{prefix}_{self._devnum}.pdf")
        try:
            from ..widgets.printer_pdf_export import estimate_pdf_page_count, save_as_pdf
            progress_label = f"Saving pdf for printer {self._devnum}..."
            total_pages = estimate_pdf_page_count(lines, PAGE_LENGTH)
            if shutdown_progress is not None:
                shutdown_progress(progress_label, 0, total_pages)
            save_as_pdf(
                lines=lines,
                path=path,
                font_filename=self._font_filename,
                page_length=PAGE_LENGTH,
                color_form=self._color_name,
                progress_callback=(
                    (lambda current, total: shutdown_progress(progress_label, current, total))
                    if shutdown_progress is not None else None
                ),
            )
            logger.info("Auto-saved printer buffer to %s", path)
        except Exception as exc:
            logger.error("Failed to auto-save printer buffer to %s: %s", path, exc)

    @Slot(bool)
    def _on_connection_changed(self, connected: bool) -> None:
        self._sync_connection_buttons(connected)

    def _on_connect_button_created(self, button) -> None:
        self._btn_connect = button
        self._on_connection_changed(self._reader.is_connected)

    def _on_disconnect_button_created(self, button) -> None:
        self._btn_disconnect = button
        self._on_connection_changed(self._reader.is_connected)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _current_colors(self):
        """Return (bar_even, bar_odd) QColors for the current color name."""
        _, light = PAPER_COLORS.get(self._color_name, PAPER_COLORS["GREEN"])
        return BAR_EVEN, light

    def _default_line_delay_ms(self) -> int:
        return DEFAULT_3215_LINE_DELAY_MS if self._is_3215 else DEFAULT_1403_LINE_DELAY_MS

    def _default_blank_line_delay_ms(self) -> int:
        return DEFAULT_3215_BLANK_LINE_DELAY_MS if self._is_3215 else DEFAULT_1403_BLANK_LINE_DELAY_MS

    def _load_delay_ms(self, *, key: str, default: int, label: str) -> int:
        """Return a non-negative per-device printer pacing delay in milliseconds."""
        if self._config is None:
            return default
        raw = self._config.get_setting("devices", key, "")
        if raw == "":
            self._config.set_setting("devices", key, str(default))
            return default
        try:
            return max(0, int(float(raw)))
        except (TypeError, ValueError):
            logger.warning(
                "Invalid %s for %s: %r; using default %s ms",
                label,
                self._devnum,
                raw,
                default,
            )
            self._config.set_setting("devices", key, str(default))
            return default

    def _delay_ms_for_line(self, line: str) -> int:
        """Blank or whitespace-only lines print faster than content lines."""
        return self._blank_line_delay_ms if not line.strip() else self._line_delay_ms

    def _clear_buffer(self) -> None:
        """Clear all accumulated lines and update the workspace."""
        self._all_lines.clear()
        self._mini_lines.clear()
        self._queued_lines.clear()
        self._print_timer.stop()
        self._saved = True
        if self._workspace is not None:
            self._workspace._update_display.emit([], True)
        self.request_room_repaint()

    def _enqueue_line(self, line: str) -> None:
        self._queued_lines.append(line)
        if not self._print_timer.isActive():
            self._schedule_next_line()

    def _enqueue_page_eject(self) -> None:
        """Queue blank lines until the next page boundary."""
        line_count = len(self._all_lines) + len(self._queued_lines)
        remainder = line_count % PAGE_LENGTH
        pad_count = (PAGE_LENGTH - remainder) if remainder != 0 else PAGE_LENGTH
        for _ in range(pad_count):
            self._enqueue_line("")

    def _enqueue_form_feed(self) -> None:
        """Advance to the next top-of-form position unless already there."""
        line_count = len(self._all_lines) + len(self._queued_lines)
        if line_count == 0 or line_count % PAGE_LENGTH == 0:
            return
        self._enqueue_page_eject()

    def _schedule_next_line(self) -> None:
        if not self._queued_lines:
            return
        next_delay_ms = self._delay_ms_for_line(self._queued_lines[0])
        if next_delay_ms <= 0:
            self._drain_print_queue()
            return
        self._print_timer.start(next_delay_ms)

    @Slot()
    def _drain_print_queue(self) -> None:
        """Deliver queued lines into the local printer buffer at the configured pace."""
        if self._print_timer.isActive():
            self._print_timer.stop()
        while self._queued_lines and self._delay_ms_for_line(self._queued_lines[0]) <= 0:
            self._deliver_line(self._queued_lines.popleft())
        if not self._queued_lines:
            return
        self._deliver_line(self._queued_lines.popleft())
        if self._queued_lines:
            self._schedule_next_line()

    @staticmethod
    def _test_line(label: str, value: object = "") -> str:
        text = f"{label:<28} {value}".rstrip()
        return text[:PAGE_WIDTH]

    def _build_test_ruler_lines(self) -> list[str]:
        columns = PAGE_WIDTH
        printer_name = "IBM 3215 Console Printer" if self._is_3215 else "IBM 1403 Line Printer"
        header = f"HERA PRINTER TEST  {printer_name}  DEVICE {self._devnum or 'UNKNOWN'}"
        note = "The ruler below should end at column 132 with the right border visible."
        boundary = "|" + ("-" * (columns - 2)) + "|"
        tens = "".join(str((column // 10) % 10) if column >= 10 else " " for column in range(1, columns + 1))
        ones = "".join(str(column % 10) for column in range(1, columns + 1))
        sample = "".join(chr(ord("A") + ((column - 1) % 26)) for column in range(1, columns + 1))
        return [header, note, boundary, tens, ones, sample, boundary]

    def _build_test_info_lines(self) -> list[str]:
        mode_name = "3215" if self._is_3215 else "1403"
        socket_endpoint = f"{self._host}:{self._port}"
        config_endpoint = f"{self._config.host}:{self._config.port}" if self._config is not None else "n/a"
        config_order = ", ".join(self._config.device_order) if self._config and self._config.device_order else "default"
        api_base_url = self._config.api_base_url if self._config is not None else "n/a"
        info_lines = [
            "HERA SYSTEM DIAGNOSTICS",
            "",
            self._test_line("Generated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            self._test_line("Printer mode", mode_name),
            self._test_line("Printer name", "IBM 3215 Console Printer" if self._is_3215 else "IBM 1403 Line Printer"),
            self._test_line("Device class", self.devclass or "PRT"),
            self._test_line("Device type", self.devtype or "unknown"),
            self._test_line("Device number", self._devnum or "UNKNOWN"),
            self._test_line("Bitmap", self.bitmap_name),
            self._test_line("Host", self._host),
            self._test_line("Socket port", self._port),
            self._test_line("Socket endpoint", socket_endpoint),
            self._test_line("Socket connected", "yes" if self._reader.is_connected else "no"),
            self._test_line("REST API endpoint", config_endpoint),
            self._test_line("REST API base URL", api_base_url),
            self._test_line("API client attached", "yes" if self._api_client is not None else "no"),
            self._test_line("Paper color", self._color_name),
            self._test_line("Font file", self._font_filename),
            self._test_line("Font family", self._font_family or "default"),
            self._test_line("Mini font px", self._mini_font_px),
            self._test_line("Workspace side margin", WORKSPACE_SIDE_MARGIN_CHARS),
            self._test_line("Mini side margin", MINI_SIDE_MARGIN_CHARS),
            self._test_line("Mini max lines", self._mini_max_lines),
            self._test_line("Mini columns", PAGE_WIDTH),
            self._test_line("Mini rotation", self._mini_rotation),
            self._test_line("Page length", PAGE_LENGTH),
            self._test_line("Line delay ms", self._line_delay_ms),
            self._test_line("Blank line delay ms", self._blank_line_delay_ms),
            self._test_line("Queued lines", len(self._queued_lines)),
            self._test_line("Buffered lines", len(self._all_lines)),
            self._test_line("Saved", "yes" if self._saved else "no"),
            self._test_line("Workspace created", "yes" if self._workspace is not None else "no"),
            self._test_line("Pending command", self._pending_command or "none"),
            self._test_line("Command input", "enabled" if self._is_3215 else "disabled"),
            self._test_line("Config host", self._config.host if self._config is not None else "n/a"),
            self._test_line("Config port", self._config.port if self._config is not None else "n/a"),
            self._test_line("Poll interval", self._config.poll_interval if self._config is not None else "n/a"),
            self._test_line("Tapes folder", self._config.tapes_folder if self._config is not None else "n/a"),
            self._test_line("Bitmap theme", self._config.bitmap_theme if self._config is not None else "n/a"),
            self._test_line("Room background", self._config.room_background if self._config is not None else "n/a"),
            self._test_line("Device order", config_order),
            self._test_line("Auto-save PDFs", self._config.get_setting("shutdown", "autosave_printer_pdfs", "1") if self._config is not None else "n/a"),
            self._test_line("Printer color key", f"printer_color_{self._devnum}"),
            self._test_line("Line delay key", f"printer_line_delay_ms_{self._devnum}"),
            self._test_line("Blank delay key", f"printer_blank_line_delay_ms_{self._devnum}"),
            self._test_line("Mini area", f"{self._mini_screen._w}x{self._mini_screen._h}"),
            self._test_line("Room light origin", self.room_light_origin or "none"),
            self._test_line("Reader thread", getattr(self._reader, "_thread_name", "n/a")),
            self._test_line("Working directory", os.getcwd()),
            self._test_line("End of diagnostics", "page continues below"),
        ]
        target_lines = PAGE_LENGTH - (len(self._build_test_ruler_lines()) * 2) - 2
        if len(info_lines) < target_lines:
            info_lines.extend([""] * (target_lines - len(info_lines)))
        return info_lines[:target_lines]

    def _build_test_printout_lines(self) -> list[str]:
        ruler_lines = self._build_test_ruler_lines()
        return ruler_lines + [""] + self._build_test_info_lines() + [""] + ruler_lines

    # ------------------------------------------------------------------
    # Socket line handler
    # ------------------------------------------------------------------

    def _deliver_line(self, line: str) -> None:
        """Append one delivered line to the buffer and workspace."""
        self.mark_room_activity()
        self._all_lines.append(line)
        self._mini_lines.append(line)
        if len(self._mini_lines) > self._mini_max_lines:
            self._mini_lines = self._mini_lines[-self._mini_max_lines:]
        self._saved = False
        if self._workspace is not None:
            self._workspace._update_display.emit([line], False)
        self.request_room_repaint()

    @Slot(str)
    def _on_socket_line(self, line: str) -> None:
        """Queue lines immediately; handle form feed (0x0C) wherever it appears."""
        # \x0C may be standalone, a line prefix (e.g. "\x0Cbanner text"),
        # or embedded mid-line.  Split on it and process each segment.
        if '\x0C' in line:
            parts = line.split('\x0C')
            for i, part in enumerate(parts):
                if i > 0:
                    # A \x0C preceded this segment — eject to next page.
                    # Skip eject if the buffer is empty (already at page start).
                    if self._all_lines or self._queued_lines:
                        self._enqueue_page_eject()
                if part:
                    self._enqueue_line(part)
            return

        # No form feed — regular line
        self._enqueue_line(line)

    def _on_send_command(self, cmd: str) -> None:
        self._pending_command = cmd
        self.mark_room_activity()

    def room_light_levels(self) -> Optional[list[float]]:
        if self.room_light_origin is None:
            return None
        pending = self.room_state_light(bool(self._pending_command))
        buffered = self.room_state_light(bool(self._all_lines or self._queued_lines))
        return [self.room_connected_light(), self.room_activity_level(), pending, buffered]

    def _do_connect(self) -> None:
        self._reader.connect_socket()

    def _do_disconnect(self) -> None:
        dlg = QMessageBox(
            QMessageBox.Icon.Question,
            "Disconnect Printer",
            "Disconnect the printer socket connection?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self._workspace,
        )
        dlg.setDefaultButton(QMessageBox.StandardButton.No)
        dlg.accepted.connect(self._on_disconnect_accepted)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        self._disconnect_dlg = dlg
        dlg.open()

    def _on_disconnect_accepted(self) -> None:
        self._disconnect_dlg = None
        self._reader.disconnect_socket()
        self._sync_connection_buttons(False)

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------

    def _do_save(self) -> bool:
        if not self._all_lines:
            return False
        from PySide6.QtWidgets import QFileDialog
        parent = self._workspace  # may be None, that's fine for the dialog
        dlg = QFileDialog(parent, "Save Printer Output", "")
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setNameFilter("PDF files (*.pdf);;All files (*)")
        dlg.setDefaultSuffix("pdf")
        if dlg.exec() != QFileDialog.Accepted:
            return False
        path = dlg.selectedFiles()[0]
        try:
            from ..widgets.printer_pdf_export import save_as_pdf
            save_as_pdf(
                lines=self._all_lines[:],
                path=path,
                font_filename=self._font_filename,
                page_length=PAGE_LENGTH,
                color_form=self._color_name,
            )
            self._saved = True
            return True
        except Exception as exc:
            logger.error("Failed to save PDF: %s", exc)
            return False

    def _do_test(self) -> None:
        if self._all_lines or self._queued_lines:
            self._enqueue_form_feed()
        for line in self._build_test_printout_lines():
            self._enqueue_line(line)
        self._enqueue_form_feed()

    def _do_discard(self) -> None:
        # Immediate clear when buffer is empty or already saved
        if (not self._all_lines and not self._queued_lines) or (self._saved and not self._queued_lines):
            self._clear_buffer()
            return

        msg = QMessageBox()
        msg.setWindowTitle("Discard Printer Output")
        msg.setText("There is unsaved content. What would you like to do?")
        save_btn    = msg.addButton("Save",           QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg.addButton("Discard Anyway", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton("Cancel",          QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == save_btn:
            ok = self._do_save()
            if ok:
                self._clear_buffer()
        elif clicked == discard_btn:
            self._clear_buffer()
        # Cancel: do nothing

    def _do_setup(self) -> None:
        """Open paper color selection dialog."""
        dlg = QDialog()
        dlg.setWindowFlags(Qt.Dialog)
        dlg.setMinimumWidth(DIALOG_MIN_WIDTH)
        dlg.setWindowTitle("Paper Color")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Select paper color:"))

        btn_row = QHBoxLayout()
        selected: dict = {"name": self._color_name}

        for name in PAPER_COLORS:
            btn_row.addWidget(self._paper_color_button(name, selected, dlg))

        layout.addLayout(btn_row)

        cancel_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        cancel_box.rejected.connect(dlg.reject)
        layout.addWidget(cancel_box)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_name = selected["name"]
        if new_name == self._color_name:
            return
        self._set_paper_colors(new_name)
