import unittest

import hardware_platform


class HardwarePlatformTests(unittest.TestCase):
    def test_null_output_is_pin_compatible(self):
        output = hardware_platform.NullOutput()
        self.assertEqual(output(), 0)
        output(1)
        self.assertEqual(output(), 1)
        output.toggle()
        self.assertEqual(output(), 0)

    def test_rp2_watchdog_timeout_is_capped(self):
        original = hardware_platform.IS_RP2
        try:
            hardware_platform.IS_RP2 = True
            self.assertEqual(hardware_platform.watchdog_timeout(9000), 8000)
        finally:
            hardware_platform.IS_RP2 = original

    def test_non_rp2_watchdog_timeout_is_not_artificially_capped(self):
        original = hardware_platform.IS_RP2
        try:
            hardware_platform.IS_RP2 = False
            self.assertEqual(hardware_platform.watchdog_timeout(15000), 15000)
        finally:
            hardware_platform.IS_RP2 = original

