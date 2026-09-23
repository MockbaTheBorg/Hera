import unittest
from unittest.mock import MagicMock

from app.devices.pch3525 import Pch3525Device


class TestPch3525PendingCards(unittest.TestCase):
    def _make_device(self):
        device = Pch3525Device.__new__(Pch3525Device)
        device._reader = None
        device._btn_connect = None
        device._btn_disconnect = None
        device._disconnect_dlg = None
        device._skip_separator_cards = True
        device._pending_cards = []
        device._deck_view = None
        device._config = None
        return device

    def test_card_received_before_workspace_is_replayed(self):
        device = self._make_device()
        device._on_line_received("A" * 80)
        device._on_line_received("B" * 10)
        self.assertEqual(device._pending_cards, ["A" * 80, "B" * 10])
        self.assertIsNone(device._deck_view)

        view = MagicMock()
        view.lines = []
        device._deck_view = view
        device.mark_room_activity = MagicMock()
        device._replay_pending_cards()

        self.assertEqual(device._pending_cards, [])
        self.assertEqual(view.append_line.call_count, 2)
        view.append_line.assert_any_call("A" * 80)
        view.append_line.assert_any_call("B" * 10 + " " * 70)
        self.assertTrue(view.changed)

    def test_separator_card_pending_is_filtered_on_replay(self):
        device = self._make_device()
        sep = "|" + "Þ" * 39 + "|" * 40
        device._on_line_received(sep)
        device._on_line_received("C" * 80)
        self.assertEqual(len(device._pending_cards), 2)

        view = MagicMock()
        view.lines = []
        device._deck_view = view
        device.mark_room_activity = MagicMock()
        device._replay_pending_cards()

        self.assertEqual(device._pending_cards, [])
        view.append_line.assert_called_once_with("C" * 80)

    def test_cards_after_workspace_are_not_buffered(self):
        device = self._make_device()
        view = MagicMock()
        view.lines = []
        device._deck_view = view
        device.mark_room_activity = MagicMock()
        device._on_line_received("D" * 80)
        self.assertEqual(device._pending_cards, [])
        view.append_line.assert_called_once_with("D" * 80)


if __name__ == "__main__":
    unittest.main()
