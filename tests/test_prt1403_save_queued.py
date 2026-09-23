import unittest
from unittest.mock import MagicMock, patch

from app.devices.prt1403 import PAGE_LENGTH, Prt1403Device


class _FakeDialog:
    Accepted = 1

    def __init__(self):
        self.accepted = True

    def setAcceptMode(self, mode):
        pass

    def setNameFilter(self, f):
        pass

    def setDefaultSuffix(self, s):
        pass

    def exec(self):
        return 1

    def selectedFiles(self):
        return ["/tmp/out.pdf"]


class TestSaveQueued(unittest.TestCase):
    def _device(self):
        with patch.object(Prt1403Device, "__init__", lambda self, context=None: None):
            dev = Prt1403Device()
        dev._all_lines = ["line1", "line2"]
        from collections import deque
        dev._queued_lines = deque(["queued1"])
        dev._saved = False  # unsaved buffered output
        dev._font_filename = "impact.ttf"
        dev._color_name = "GREEN"
        dev._workspace = None
        return dev

    def test_save_includes_queued_lines(self):
        dev = self._device()
        save_mock = MagicMock()
        fd_mock = MagicMock(return_value=_FakeDialog())
        fd_mock.Accepted = 1
        fd_mock.AcceptSave = 1
        with patch("PySide6.QtWidgets.QFileDialog", fd_mock), \
             patch("app.widgets.printer_pdf_export.save_as_pdf", save_mock):
            ok = dev._do_save()
        self.assertTrue(ok)
        fd_mock.assert_called_once()
        save_mock.assert_called_once()
        kwargs = save_mock.call_args.kwargs
        self.assertEqual(kwargs["lines"], ["line1", "line2", "queued1"])
        self.assertEqual(kwargs["page_length"], PAGE_LENGTH)
        # Queued lines were not flushed, so buffer must stay unsaved
        self.assertFalse(dev._saved)

    def test_save_empty_returns_false(self):
        with patch.object(Prt1403Device, "__init__", lambda self, context=None: None):
            dev = Prt1403Device()
        dev._all_lines = []
        from collections import deque
        dev._queued_lines = deque()
        self.assertFalse(dev._do_save())


if __name__ == "__main__":
    unittest.main()
