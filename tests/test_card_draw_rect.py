import unittest

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

from app.devices.card_common import CardWidget, _CARD_ASPECT


class TestCardDrawRect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_small_height_no_divide_by_zero(self):
        widget = CardWidget()
        widget.resize(400, 20)
        rect = widget._card_draw_rect()
        self.assertIsInstance(rect, QRectF)
        self.assertGreaterEqual(rect.width(), 0.0)
        self.assertGreaterEqual(rect.height(), 0.0)

    def test_normal_height_preserves_aspect(self):
        widget = CardWidget()
        widget.resize(400, 200)
        rect = widget._card_draw_rect()
        self.assertAlmostEqual(rect.width() / rect.height(), _CARD_ASPECT, places=3)


if __name__ == '__main__':
    unittest.main()
