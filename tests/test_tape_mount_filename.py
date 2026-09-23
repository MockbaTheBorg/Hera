"""Tests for tape filename validation in TapeDevice.mount_tape."""
import unittest

from app.devices.tape import _validate_tape_filename


class TapeMountFilenameTest(unittest.TestCase):
    def test_valid_filename(self):
        self.assertEqual(_validate_tape_filename("TAPE01.het"), "TAPE01.het")

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            _validate_tape_filename("")

    def test_absolute_path_rejected(self):
        for name in ("/etc/passwd", "/tapes/x.het", "\\tmp\\x.het"):
            with self.assertRaises(ValueError):
                _validate_tape_filename(name)

    def test_traversal_rejected(self):
        for name in ("..", "../x.het", "a/../b.het", "sub/x.het", "./x.het"):
            with self.assertRaises(ValueError):
                _validate_tape_filename(name)

    def test_null_and_whitespace_rejected(self):
        for name in ("x\x00.het", " x.het", "x.het "):
            with self.assertRaises(ValueError):
                _validate_tape_filename(name)


if __name__ == "__main__":
    unittest.main()
