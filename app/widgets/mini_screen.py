# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
MiniScreenOverlay — reusable off-screen scaled text renderer.

Renders a scrolling text display into a sub-rectangle of a device room bitmap.
Used by ConsoleDevice and terminal devices.

Supports two rendering modes:
- Solid mode (default): solid bg_color background, fg_color text.
- Green-bar mode: alternating bar_even/bar_odd band backgrounds, text_color text.
  Activated by passing bar_even (QColor) at construction.

Dynamic height support:
- When line_count > 0 is passed to render(), only the proportional area is drawn.
- top_anchored=True: area grows downward from the top (default, consoles).
- top_anchored=False: area grows upward from the bottom (printers, paper feeds up).
- When line_count=0 (default), the full area is used (backward-compatible behavior).
"""

from PySide6.QtGui import QPainter, QColor, QFontMetrics, QPixmap
from PySide6.QtCore import QRect

from .terminal_style import terminal_font


class MiniScreenOverlay:
    """Renders a scaled-down text screen into a device bitmap sub-rectangle.

    Parameters
    ----------
    x, y          : pixel offset of the screen area within the device bitmap
    w, h          : size of the screen area in device bitmap pixels
    fg_color      : text color in solid mode (default: phosphor green #33FF66)
    bg_color      : background color in solid mode (default: black)
    max_lines     : number of lines to render (last N lines of input); default 24
    max_cols      : characters per line (lines truncated to this length); default 80
    bar_even           : even-band background color for green-bar mode (default: None = solid mode)
    bar_odd            : odd-band background color for green-bar mode
    text_color         : text color for green-bar mode (default: black)
    top_anchored       : when True the content area grows downward from y; when False
                         it grows upward toward y+h (paper-feed direction)
    page_header_lines  : lines per page rendered as bar_even regardless of band
                         (default: 0 → simple every-other-line alternation)
    lines_per_band     : lines sharing one band color before switching (default: 1)
    page_length        : page length in lines; used to compute position-within-page
                         for band coloring when page_header_lines > 0 (default: 66)
    """

    def __init__(
        self,
        x: int, y: int, w: int, h: int,
        fg_color: QColor = None,
        bg_color: QColor = None,
        max_lines: int = 24,
        max_cols: int = 80,
        bar_even: QColor = None,
        bar_odd: QColor = None,
        text_color: QColor = None,
        top_anchored: bool = True,
        page_header_lines: int = 0,
        lines_per_band: int = 1,
        page_length: int = 66,
        font_family: str | None = None,
        bold: bool = False,
        opacity: float = 1.0,
        brightness_boost: float = 1.0,
    ):
        self._x = x
        self._y = y
        self._w = w
        self._h = h
        self._fg = fg_color if fg_color is not None else QColor(51, 255, 102)
        self._bg = bg_color if bg_color is not None else QColor(0, 0, 0)
        self._max_lines = max_lines
        self._max_cols = max_cols
        # Green-bar mode
        self._bar_even = bar_even
        self._bar_odd  = bar_odd  if bar_odd  is not None else QColor(221, 255, 221)
        self._text_color = text_color if text_color is not None else QColor(0, 0, 0)
        self._top_anchored = top_anchored
        self._page_header_lines = page_header_lines
        self._lines_per_band = lines_per_band
        self._page_length = page_length
        self._font_family = font_family
        self._bold = bold
        self._opacity = max(0.0, min(1.0, opacity))
        self._brightness_boost = max(1.0, float(brightness_boost))

    def _brighten_pixmap(self, pm: QPixmap) -> QPixmap:
        """Boost visible pixels without lifting the black screen background."""
        if self._brightness_boost <= 1.0:
            return pm
        img = pm.toImage()
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if max(c.red(), c.green(), c.blue()) <= 24:
                    continue
                c.setRed(min(255, int(c.red() * self._brightness_boost)))
                c.setGreen(min(255, int(c.green() * self._brightness_boost)))
                c.setBlue(min(255, int(c.blue() * self._brightness_boost)))
                img.setPixelColor(x, y, c)
        return QPixmap.fromImage(img)

    def _band_color(self, abs_line: int) -> QColor:
        """Return the band background color for an absolute line index."""
        if self._page_header_lines == 0:
            # Simple every-other-line alternation (console / backward-compat mode)
            return self._bar_even if abs_line % 2 == 0 else self._bar_odd
        pos = abs_line % self._page_length
        if pos < self._page_header_lines:
            return self._bar_even
        adjusted = pos - self._page_header_lines
        band = (adjusted // self._lines_per_band) % 2
        return self._bar_odd if band == 0 else self._bar_even

    def render(
        self,
        painter: QPainter,
        device_rect: QRect,
        lines: list,
        line_count: int = 0,
        rotate_180: bool = False,
        highlights: list | None = None,
    ) -> None:
        """Draw the mini-screen into the screen area.

        Parameters
        ----------
        painter     : active QPainter on the room canvas
        device_rect : bounding rect of the device bitmap on the canvas
        lines       : list of text strings (last max_lines are used)
        line_count  : number of logical lines printed so far; 0 = fill full height
                      (backward-compatible default for console devices)
        rotate_180  : when True the pixmap is drawn upside-down (1403 paper direction)
        """
        if not lines and line_count == 0:
            return

        # Determine how many lines to show and how tall the visible area is
        if line_count == 0:
            # Backward-compatible: always full height
            visible_lines = min(len(lines), self._max_lines)
            visible_h = self._h
        else:
            visible_lines = min(line_count, self._max_lines)
            visible_h = round(visible_lines / self._max_lines * self._h)

        if visible_h == 0:
            return

        # At minimum 1 px per line; cap visible_lines to what fits in the pixmap
        # so that no lines are silently clipped when max_h < max_lines.
        visible_lines = min(visible_lines, visible_h)

        # Take the last visible_lines from the input
        display_lines = lines[-visible_lines:] if len(lines) >= visible_lines else lines

        # Absolute index of the first displayed line (for band-color sync with page layout)
        abs_line_base = (line_count - visible_lines) if line_count > 0 else 0

        # Compute screen rect based on anchor direction
        if self._top_anchored:
            screen_x = device_rect.x() + self._x
            screen_y = device_rect.y() + self._y
        else:
            bottom = device_rect.y() + self._y + self._h
            screen_x = device_rect.x() + self._x
            screen_y = bottom - visible_h

        screen_rect = QRect(screen_x, screen_y, self._w, visible_h)

        line_px = max(1, visible_h // max(1, visible_lines))

        pm = QPixmap(self._w, visible_h)

        if self._bar_even is not None:
            # Green-bar mode
            pm.fill(self._bar_even)
            p = QPainter(pm)
            font = terminal_font(line_px)
            if self._font_family:
                font.setFamily(self._font_family)
            font.setPixelSize(line_px)
            if self._bold:
                font.setBold(True)
            p.setFont(font)
            for i, line in enumerate(display_lines):
                bg = self._band_color(abs_line_base + i)
                line_fg = None
                if highlights:
                    for pattern, h_fg, h_bg in highlights:
                        if pattern.match(line):
                            if h_bg is not None:
                                bg = h_bg
                            line_fg = h_fg
                            break
                p.fillRect(0, i * line_px, self._w, line_px, bg)
                p.setPen(line_fg if line_fg is not None else self._text_color)
                p.drawText(0, (i + 1) * line_px, line[:self._max_cols])
        else:
            # Solid mode
            pm.fill(self._bg)
            p = QPainter(pm)
            font = terminal_font(line_px)
            if self._font_family:
                font.setFamily(self._font_family)
            font.setPixelSize(line_px)
            if self._bold:
                font.setBold(True)
            p.setFont(font)
            for i, line in enumerate(display_lines):
                line_fg = None
                if highlights:
                    for pattern, h_fg, h_bg in highlights:
                        if pattern.match(line):
                            if h_bg is not None:
                                p.fillRect(0, i * line_px, self._w, line_px, h_bg)
                            line_fg = h_fg
                            break
                p.setPen(line_fg if line_fg is not None else self._fg)
                p.drawText(0, (i + 1) * line_px, line[:self._max_cols])

        p.end()
        pm = self._brighten_pixmap(pm)

        painter.save()
        painter.setOpacity(self._opacity)
        if rotate_180:
            painter.translate(screen_rect.x() + self._w, screen_rect.y() + visible_h)
            painter.scale(-1, -1)
            painter.drawPixmap(0, 0, pm)
        else:
            painter.drawPixmap(screen_rect, pm)
        painter.restore()

    def render_cells(
        self,
        painter: QPainter,
        device_rect: QRect,
        cells: list,
        *,
        rows: int,
        cols: int,
    ) -> None:
        if not cells:
            return

        # Dynamic font size: fit rows into available height, same as render()
        line_px = max(1, self._h // max(1, rows))
        font = terminal_font(line_px)
        if self._font_family:
            font.setFamily(self._font_family)
        if self._bold:
            font.setBold(True)
        font.setPixelSize(line_px)
        metrics = QFontMetrics(font)
        cell_w = max(1, metrics.horizontalAdvance("M"))
        cell_h = max(1, metrics.height())
        ascent = metrics.ascent()

        target_rect = QRect(device_rect.x() + self._x, device_rect.y() + self._y, self._w, self._h)
        pm = QPixmap(cell_w * cols, cell_h * rows)
        p = QPainter(pm)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(font)

        for addr in range(min(len(cells), rows * cols)):
            row, col = divmod(addr, cols)
            x = col * cell_w
            y = row * cell_h
            char, fg, bg, underscore = cells[addr]
            p.fillRect(x, y, cell_w, cell_h, bg)
            if char != " ":
                p.setPen(fg)
                p.drawText(x, y + ascent, char)
            if underscore:
                p.setPen(fg)
                p.drawLine(x, y + cell_h - 2, x + cell_w - 1, y + cell_h - 2)

        p.end()
        pm = self._brighten_pixmap(pm)
        painter.save()
        painter.setOpacity(self._opacity)
        painter.drawPixmap(target_rect, pm)
        painter.restore()
