import unittest
from unittest.mock import MagicMock

from app.devices.dasd import DasdDevice


class _Device(DasdDevice):
    def __init__(self):
        # Skip DeviceBase/Qt-dependent initialisation
        self._mounted = False
        self._vol_label = ""
        self._last_assignment = None
        self.repaints = 0

    def request_room_repaint(self):
        self.repaints += 1

    def mark_room_activity(self):
        pass

    def room_device_info(self):
        return self.info


class TestDasdRepaint(unittest.TestCase):
    def test_repaint_on_change(self):
        d = _Device()
        d.info = {"assignment": "*64* z24min/sares1.cckd [cu 3990-6]"}
        d.poll(None)
        self.assertTrue(d._mounted)
        self.assertEqual(d._vol_label, "SARES1")
        self.assertEqual(d.repaints, 1)

        # unchanged poll: no repaint
        d.poll(None)
        self.assertEqual(d.repaints, 1)

        # change again: repaint
        d.info = {"assignment": ""}
        d.poll(None)
        self.assertFalse(d._mounted)
        self.assertEqual(d.repaints, 2)


if __name__ == "__main__":
    unittest.main()
