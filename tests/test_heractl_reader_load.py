import os
import unittest
from unittest import mock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import heractl


class ReaderLoadTest(unittest.TestCase):
    def test_missing_file_raises_api_error(self):
        args = mock.Mock(file=os.path.join("no", "such", "file.txt"), line=None, device="0")
        with self.assertRaises(heractl.ApiError) as ctx:
            heractl.act_reader_load(mock.Mock(), args)
        self.assertIn("Cannot read", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
