import unittest

from app.devices.cpu import CpuDevice


class RegisterRowsTest(unittest.TestCase):
    def test_valid_hex_gpr(self):
        regs = {f"GR{i}": f"{i * 0x1111111111111111:016X}" for i in range(16)}
        rows = CpuDevice._register_rows(regs, "GR")
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows[0], 0)
        self.assertEqual(rows[1], 0x1111111111111111)

    def test_malformed_gpr_falls_back(self):
        regs = {f"GR{i}": "0" for i in range(16)}
        regs["GR3"] = "not-hex!"
        regs["GR5"] = None
        regs["GR7"] = ""
        rows = CpuDevice._register_rows(regs, "GR")
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows[3], 0)
        self.assertEqual(rows[5], 0)
        self.assertEqual(rows[7], 0)
        self.assertEqual(rows[0], 0)

    def test_valid_fpr_float_conversion(self):
        import struct
        regs = {f"FPR{i}": "0" for i in range(16)}
        regs["FPR2"] = "1.5"
        rows = CpuDevice._register_rows(regs, "FPR")
        expected = struct.unpack(">Q", struct.pack(">d", 1.5))[0]
        self.assertEqual(rows[2], expected)

    def test_malformed_fpr_falls_back(self):
        regs = {f"FPR{i}": "0" for i in range(16)}
        regs["FPR4"] = "zz-not-a-number"
        rows = CpuDevice._register_rows(regs, "FPR")
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows[4], 0)


if __name__ == "__main__":
    unittest.main()
