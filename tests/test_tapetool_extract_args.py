import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import tapetool


class ExtractArgsTest(unittest.TestCase):
    def test_invalid_dataset_number(self):
        with self.assertRaises(tapetool.TapeToolError):
            tapetool.main(["-e", "out.bin", "abc"])

    def test_invalid_member_number(self):
        with self.assertRaises(tapetool.TapeToolError):
            tapetool.main(["-e", "out.bin", "1", "xyz"])


if __name__ == "__main__":
    unittest.main()
