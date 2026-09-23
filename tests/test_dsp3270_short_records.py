import unittest

from app.devices.dsp3270_session import Tn3270Session


class ShortRecordTests(unittest.TestCase):
    def _session(self):
        return Tn3270Session()

    def test_one_byte_records_do_not_raise(self):
        s = self._session()
        for cmd in (0xF5, 0x7E, 0xF1, 0x11, 0x6F, 0x03, 0x40):
            try:
                s._process_record(bytes([cmd]))
            except IndexError as exc:
                self.fail(f"IndexError for command 0x{cmd:02x}: {exc}")

    def test_truncated_records_do_not_raise(self):
        s = self._session()
        s._process_record(b"")
        s._process_record(bytes([0xF5]))  # EW
        s._process_record(bytes([0x7E]))  # EWA
        s._process_record(bytes([0x11]))  # W
        s._process_record(bytes([0x40]))  # WSF
        s._process_record(bytes([0x40, 0x00]))  # WSF with truncated SF length


if __name__ == "__main__":
    unittest.main()
