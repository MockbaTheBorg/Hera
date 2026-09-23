import unittest

from tools.tapetool import TapeToolError, bdw_length


class BdwLengthTests(unittest.TestCase):
    def test_empty_raises(self):
        with self.assertRaises(TapeToolError):
            bdw_length(b"")

    def test_short_high_bit_raises(self):
        for data in (b"\x80", b"\x80\x00", b"\x80\x00\x01"):
            with self.assertRaises(TapeToolError):
                bdw_length(data)

    def test_low_bit_two_bytes(self):
        self.assertEqual(bdw_length(b"\x00\x50"), 0x50)

    def test_high_bit_four_bytes(self):
        self.assertEqual(bdw_length(b"\x80\x00\x10\x02"), 0x800001002 & 0x7FFFFFFF)
        self.assertEqual(bdw_length(b"\x80\x00\x00\x10"), 0x10)


if __name__ == "__main__":
    unittest.main()
