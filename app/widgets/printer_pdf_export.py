# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
printer_pdf_export — faithful IBM fan-fold paper PDF renderer using fpdf2.

Renders printer output as a styled PDF matching the prt1403 reference paper layout:
alternating green-bar bands, tractor-hole circles, border lines, and margin numbers.

Page size: 14.5" × 11" (1044 × 792 pt) in portrait orientation.
"""

import logging
import os

logger = logging.getLogger(__name__)

# ── Paper dimensions (pt) ────────────────────────────────────────────────────
PAGE_W      = 1044   # 14.5 inches
PAGE_H      = 792    # 11 inches
PAGE_COLS   = 132
PAGE_LINES  = 66
TOP_MARGIN  = 72     # header / preprint area above text

# ── Paper color palettes — (dark_rgb, light_rgb) tuples ─────────────────────
# Matching prt1403 reference palette values.
PAPER_COLORS = {
    "GREEN":  ((99,  182,  99), (219, 250, 219)),
    "BLUE":   ((65,  182, 255), (214, 239, 255)),
    "ORANGE": ((219, 182,  99), (255, 221, 146)),
    "GRAY":   ((200, 200, 200), (230, 230, 230)),
    "WHITE":  ((255, 255, 255), (255, 255, 255)),
}

_FREE_HOLE_RADIUS = 5.5   # normal tractor hole radius (pt)


def _font_path(font_filename: str = "") -> str:
    """Return path to the printer font.

    If *font_filename* is given (e.g. 'dotmatrix.ttf' or 'impact.ttf'), that
    file is tried first in fonts/.  Falls back to the 1403 default candidates
    when the requested file is not found.
    """
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = []
    if font_filename:
        candidates.append(os.path.join(base, "fonts", font_filename))
    candidates += [
        os.path.join(base, "fonts", "impact.ttf"),
        os.path.join(base, "fonts", "IBM140310Pitch-Regular-MRW.ttf"),
        os.path.join(base, "originals", "prt1403", "fonts", "IBMPlexMono-Regular.ttf"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def _draw_form(pdf, color_name: str) -> None:
    """Draw page background: alternating bands, border lines, margin numbers."""
    dark, light = PAPER_COLORS.get(color_name, PAPER_COLORS["GREEN"])

    pdf.set_draw_color(*dark)
    pdf.set_fill_color(*light)
    pdf.set_text_color(*dark)
    pdf.set_font("helvetica", "", 7)

    # 10 filled alternating bands, each 36 pt tall, starting at TOP_MARGIN
    for i in range(10):
        pdf.rect(40, TOP_MARGIN + i * 72 - 0.5, PAGE_W - 80, 36, "F")

    # Horizontal lines every 36 pt across the band area
    pdf.set_line_width(0.7)
    pdf.line(30 - 0.25, TOP_MARGIN - 0.5, PAGE_W - 30 + 0.25, TOP_MARGIN - 0.5)
    pdf.line(30 - 0.25, PAGE_H - 1 - 0.5, PAGE_W - 30 + 0.25, PAGE_H - 1 - 0.5)
    for i in range(20):
        pdf.line(40, TOP_MARGIN + 36 * i - 0.5, PAGE_W - 40, TOP_MARGIN + 36 * i - 0.5)

    # Vertical border lines
    pdf.set_line_width(0.5)
    pdf.line(30 - 0.5, TOP_MARGIN - 0.5, 30 - 0.5, PAGE_H - 1 - 0.5)
    pdf.line(40,       TOP_MARGIN - 0.5, 40,       PAGE_H - 1 - 0.5)
    pdf.line(PAGE_W - 30 + 0.5, TOP_MARGIN - 0.5, PAGE_W - 30 + 0.5, PAGE_H - 1 - 0.5)
    pdf.line(PAGE_W - 40,       TOP_MARGIN - 0.5, PAGE_W - 40,       PAGE_H - 1 - 0.5)

    # Left margin line numbers 1–60
    for i in range(60):
        pdf.set_xy(30, TOP_MARGIN + i * 12)
        w = 9.7 if i >= 9 else 10
        pdf.cell(w, 12, text=str(i + 1), align="C")


def _draw_holes(pdf, color_name: str) -> None:
    """Draw 22 tractor holes per side; top and bottom are slightly larger."""
    dark, light = PAPER_COLORS.get(color_name, PAPER_COLORS["GRAY"])

    pdf.set_draw_color(*dark)
    pdf.set_fill_color(*light)
    pdf.set_line_width(0.75)

    # Top hole (larger)
    y = 18.0
    pdf.circle(20,          y, _FREE_HOLE_RADIUS + 1, "FD")
    pdf.circle(PAGE_W - 20, y, _FREE_HOLE_RADIUS + 1, "FD")

    # Bottom hole (larger)
    y = 18.0 + 36.0 * 21
    pdf.circle(20,          y, _FREE_HOLE_RADIUS + 1, "FD")
    pdf.circle(PAGE_W - 20, y, _FREE_HOLE_RADIUS + 1, "FD")

    # Middle holes
    for i in range(1, 21):
        y = 18.0 + 36.0 * i
        pdf.circle(20,          y, _FREE_HOLE_RADIUS, "FD")
        pdf.circle(PAGE_W - 20, y, _FREE_HOLE_RADIUS, "FD")


def _draw_page(pdf, lines: list, font_size: float, line_h: float, color_form: str, color_holes: str) -> None:
    """Render one page: background, holes, then text."""
    pdf.add_page()
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)

    _draw_form(pdf, color_form)
    _draw_holes(pdf, color_holes)

    # Text — 66 lines across the full page height (matches prt1403 reference).
    # Baseline = (lineNr - 0.25) * line_h  ≡  (i + 0.75) * line_h  for i=0..65.
    # Lines 1-6 land in the white header zone; lines 7-66 in the banded area.
    pdf.set_font("prt1403Font", size=font_size)
    pdf.set_text_color(0, 0, 0)

    for i, line in enumerate(lines[:PAGE_LINES]):
        text = line[:PAGE_COLS]
        if text:
            pdf.text(43, (i + 0.75) * line_h, text)


def save_as_pdf(
    lines: list,
    path: str,
    font_family: str = "",
    font_filename: str = "",
    bar_even=None,
    bar_odd=None,
    page_length: int = PAGE_LINES,
    color_form: str = "GREEN",
    color_holes: str = "GRAY",
) -> None:
    """Render *lines* as a faithful IBM fan-fold paper PDF and write to *path*.

    Parameters
    ----------
    lines         : list of text strings; '\\x0C' entries trigger explicit page breaks
    path          : output PDF file path
    font_family   : device font family name (unused at render time; kept for callers)
    font_filename : TTF filename in fonts/ directory (e.g. 'dotmatrix.ttf'); used to
                    select the correct typeface for the PDF output
    bar_even      : ignored (color controlled by color_form)
    bar_odd       : ignored (color controlled by color_form)
    page_length   : lines per page (default 66)
    color_form    : paper color key from PAPER_COLORS (default 'GREEN')
    color_holes   : hole color key from PAPER_COLORS (default 'GRAY')
    """
    from fpdf import FPDF  # noqa: PLC0415

    # Text fills the FULL page height: 66 lines × 12 pt = 792 pt.
    # Lines 1-6 land in the header zone (y=0-72, white), lines 7-66 land in the
    # banded area — exactly matching the prt1403 reference layout (lineNr*12-3).
    # Font size = 9 pt (= 12 pt line pitch × 0.75).
    line_h = PAGE_H / PAGE_LINES   # 792/66 = 12.0 pt
    font_size = round(line_h * 0.75, 1)  # 9.0 pt

    font_file = _font_path(font_filename)

    pdf = FPDF(orientation="P", unit="pt", format=[PAGE_W, PAGE_H])
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)

    if font_file:
        pdf.add_font("prt1403Font", "", font_file)
    else:
        # Fallback: register Courier under our alias
        pdf.add_font("prt1403Font", style="", fname="Courier")

    # Split lines into pages of page_length each, honouring \x0C breaks
    pages: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if line == "\x0C":
            # Flush current page (even if empty, FF advances to next page)
            pages.append(current)
            current = []
        else:
            current.append(line)
            if len(current) >= page_length:
                pages.append(current)
                current = []

    if current:
        pages.append(current)

    if not pages:
        pages = [[]]

    for page_lines in pages:
        _draw_page(pdf, page_lines, font_size, line_h, color_form, color_holes)

    pdf.output(path)
    logger.debug("PDF written: %s (%d pages, %d lines)", path, len(pages), len(lines))
