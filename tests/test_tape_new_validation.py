import unittest

from app.devices.tape import _validate_tape_new_args


class ValidateTapeNewArgsTest(unittest.TestCase):
    def test_valid_inputs(self):
        self.assertEqual(
            _validate_tape_new_args("TAPE001.aws", "TAPE01", "OWNER1"),
            "TAPE001.aws",
        )

    def test_valid_no_owner(self):
        self.assertEqual(_validate_tape_new_args("tape.aws", "VOLSER"), "tape.aws")

    def test_malicious_filename(self):
        for bad in ["x;rm -rf /", "x&&y", "x|y", "$(id)", "`id`", "..", "a/b"]:
            with self.assertRaises(ValueError, msg=bad):
                _validate_tape_new_args(bad, "VOLSER")

    def test_malicious_volser(self):
        for bad in ["VO;LSER", "VO&LS", "$(id)", "V OS"]:
            with self.assertRaises(ValueError, msg=bad):
                _validate_tape_new_args("t.aws", bad)

    def test_malicious_owner(self):
        for bad in ["own;er", "own$er", "own'er"]:
            with self.assertRaises(ValueError, msg=bad):
                _validate_tape_new_args("t.aws", "VOLSER", owner=bad)

    def test_empty_values(self):
        with self.assertRaises(ValueError):
            _validate_tape_new_args("", "VOLSER")
        with self.assertRaises(ValueError):
            _validate_tape_new_args("t.aws", "")


if __name__ == "__main__":
    unittest.main()
