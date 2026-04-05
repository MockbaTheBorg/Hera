# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
GreenBarPaper — QTextEdit subclass that renders alternating colored bands
behind printed text, emulating classic green-bar continuous-form paper.

Band colors are embedded in each paragraph's QTextBlockFormat so Qt handles
all rendering. Perforation markers are inserted as thin gray blocks at each
page boundary.
"""

from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor

from ..theme import SCROLLBAR_QSS


_PERF_COLOR = QColor(180, 180, 180)


class GreenBarPaper(QTextEdit):
    """
    QTextEdit with alternating per-line background bands and optional
    page-break perforation markers.

    Parameters
    ----------
    bar_even          : color for uncolored bands (default: white)
    bar_odd           : color for colored bands (default: #DDFFDD)
    lines_per_band    : consecutive lines sharing the same band color (default: 3)
    page_header_lines : lines at the start of each page that always use bar_even
                        (simulates the pre-print header zone on fan-fold paper; default: 6)
    font_family       : font family name to use; falls back to Courier New when empty
    page_length       : insert a perforation block every N lines; 0 = disabled (default: 0)
    """

    def __init__(
        self,
        bar_even: QColor = None,
        bar_odd: QColor = None,
        lines_per_band: int = 3,
        page_header_lines: int = 6,
        font_family: str = "",
        page_length: int = 0,
        side_margin_chars: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self._bar_even = bar_even if bar_even is not None else QColor(255, 255, 255)
        self._bar_odd  = bar_odd  if bar_odd  is not None else QColor(221, 255, 221)
        self._lines_per_band = max(1, lines_per_band)
        self._page_header_lines = max(0, page_header_lines)
        self._page_length = max(0, page_length)
        self._side_margin_chars = max(0, side_margin_chars)
        self._raw_lines: list[str] = []
        self._line_count = 0   # text lines (not counting perf blocks)
        self._band_pos = 0     # position within current page for band cycling

        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        font = QFont(font_family or "Courier New")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        font.setPixelSize(13)
        self.setFont(font)

        self.setStyleSheet(
            f"QTextEdit {{"
            f"  color: #000000;"
            f"  border: 1px solid #999;"
            f"}}"
            + SCROLLBAR_QSS
        )

    # ------------------------------------------------------------------
    # Band color helpers
    # ------------------------------------------------------------------

    def _band_color(self, band_pos: int) -> QColor:
        """Return band background color for the given position within a page.

        First ``page_header_lines`` positions always use bar_even (white header
        zone). After that, lines alternate in groups of ``lines_per_band``,
        starting with bar_odd (colored band) then bar_even, matching the
        prt1403 PDF layout where the first content band after the header is
        the colored band.
        """
        if band_pos < self._page_header_lines:
            return self._bar_even
        adjusted = band_pos - self._page_header_lines
        band = (adjusted // self._lines_per_band) % 2
        return self._bar_odd if band == 0 else self._bar_even

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append_line(self, text: str) -> None:
        """Append one line with correct band background; insert perf at page boundary."""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Insert perforation block at each page boundary
        if self._page_length > 0 and self._line_count > 0 and self._line_count % self._page_length == 0:
            perf_fmt = QTextBlockFormat()
            perf_fmt.setBackground(_PERF_COLOR)
            perf_fmt.setTopMargin(2)
            perf_fmt.setBottomMargin(2)
            cursor.insertBlock(perf_fmt, QTextCharFormat())
            cursor.insertText("")
            self._band_pos = 0  # reset band cycling at page start
            cursor.movePosition(QTextCursor.MoveOperation.End)

        block_fmt = QTextBlockFormat()
        block_fmt.setBackground(self._band_color(self._band_pos))

        if self._line_count == 0:
            cursor.setBlockFormat(block_fmt)
        else:
            cursor.insertBlock(block_fmt, QTextCharFormat())

        self._raw_lines.append(text)
        margin = " " * self._side_margin_chars
        cursor.insertText(f"{margin}{text}{margin}")
        self._line_count += 1
        self._band_pos += 1

        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def set_lines(self, lines: list) -> None:
        """Replace all content and re-render from line 0."""
        self._raw_lines = []
        self._line_count = 0
        self._band_pos = 0
        self.clear()
        for line in lines:
            self.append_line(line)

    def get_lines(self) -> list[str]:
        """Return all text lines as a list (perf markers excluded)."""
        return self._raw_lines[:]

    def set_colors(self, bar_even: QColor, bar_odd: QColor) -> None:
        """Update band colors and re-render all existing lines."""
        self._bar_even = bar_even
        self._bar_odd = bar_odd
        lines = self.get_lines()
        self.set_lines(lines)
