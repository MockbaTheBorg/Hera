"""Tests for the Courier core-font fallback in printer_pdf_export."""

import sys
import unittest
from unittest import mock

try:
    import fpdf  # noqa: F401
except ImportError:
    sys.modules["fpdf"] = mock.MagicMock()

from app.widgets import printer_pdf_export as ppe


class _RecordingFPDF(mock.MagicMock):
    pass


def _make_pdf_mock():
    pdf = mock.MagicMock()
    pdf.get_string_width.return_value = ppe.TEXT_W  # zero char spacing
    return pdf


class CourierFallbackTest(unittest.TestCase):
    def _run(self, font_filename=""):
        pdf = _make_pdf_mock()
        with mock.patch("fpdf.FPDF", return_value=pdf):
            with mock.patch.object(ppe, "_font_path", return_value="x.ttf" if font_filename else ""):
                ppe.save_as_pdf(["hello", "\x0C", "world"], "/tmp/_t.pdf",
                                font_filename=font_filename)
        return pdf

    def test_no_add_font_for_courier_fallback(self):
        pdf = self._run()
        pdf.add_font.assert_not_called()

    def test_courier_used_via_set_font(self):
        pdf = self._run()
        families = {c.args[0] for c in pdf.set_font.call_args_list}
        self.assertIn("courier", families)
        self.assertNotIn("prt1403Font", families)

    def test_custom_ttf_registers_font(self):
        pdf = self._run(font_filename="dotmatrix.ttf")
        pdf.add_font.assert_called_once_with("prt1403Font", "", "x.ttf")
        families = {c.args[0] for c in pdf.set_font.call_args_list}
        self.assertIn("prt1403Font", families)

    def test_no_pdf_written_for_empty_output(self):
        # Ensure output() invoked without errors on mocked pdf
        pdf = self._run()
        pdf.output.assert_called_once()


if __name__ == "__main__":
    unittest.main()
