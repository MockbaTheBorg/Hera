import unittest
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication, QWidget

from app.device_area import Workspace


class WorkspaceDisposalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_set_content_disposes_old_widget(self):
        workspace = Workspace()
        old = QWidget()
        old.deleteLater = MagicMock()
        new = QWidget()
        workspace.set_content(old)
        old.deleteLater.reset_mock()
        workspace.set_content(new)
        old.deleteLater.assert_called_once()


if __name__ == "__main__":
    unittest.main()
