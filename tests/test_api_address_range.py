import unittest

from app.scripting.errors import ApiError
from app.scripting.routes import _parse_hex_address


class ParseHexAddressTests(unittest.TestCase):
    def test_valid_addresses(self):
        for raw, expected in [
            (0, 0x000),
            (0xFFF, 0xFFF),
            ("000", 0x000),
            ("FFF", 0xFFF),
            ("0x123", 0x123),
            ("abc", 0xABC),
            (4095, 4095),
        ]:
            self.assertEqual(_parse_hex_address(raw), expected)

    def test_out_of_range_addresses(self):
        for raw in (-1, 4096, "1000", "0x1000", "-1", "FFFF"):
            with self.assertRaises(ApiError):
                _parse_hex_address(raw)

    def test_invalid_addresses(self):
        for raw in ("", "xyz", None):
            with self.assertRaises(ApiError):
                _parse_hex_address(raw)


if __name__ == "__main__":
    unittest.main()
