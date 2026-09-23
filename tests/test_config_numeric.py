import unittest

from app.config import Config


class _Section:
    def __init__(self, value):
        self.value = value

    def get(self, key, default):
        return self.value


class NumericValueTest(unittest.TestCase):
    def test_int_value_malformed_returns_default(self):
        self.assertEqual(Config._int_value(_Section("abc"), "port", 8081), 8081)

    def test_float_value_malformed_returns_default(self):
        self.assertAlmostEqual(
            Config._float_value(_Section("fast"), "poll_interval", 0.25), 0.25
        )

    def test_valid_values_converted(self):
        self.assertEqual(Config._int_value(_Section("123"), "port", 1), 123)
        self.assertAlmostEqual(Config._float_value(_Section("0.5"), "p", 1.0), 0.5)


if __name__ == "__main__":
    unittest.main()
