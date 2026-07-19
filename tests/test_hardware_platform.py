import unittest

import hardware_platform


class HardwarePlatformTests(unittest.TestCase):
    def test_firmware_ota_reports_missing_inactive_partition(self):
        class RunningPartition:
            def info(self):
                return (0, 0, 0, 0x200000, 'factory', False)

            def get_next_update(self):
                return None

        class Esp32:
            class Partition:
                RUNNING = 1

                def __new__(cls, identifier):
                    return RunningPartition()

        original_is_esp32_s3 = hardware_platform.IS_ESP32_S3
        original_esp32 = hardware_platform.esp32
        try:
            hardware_platform.IS_ESP32_S3 = True
            hardware_platform.esp32 = Esp32
            capability = hardware_platform.firmware_ota_capability()
        finally:
            hardware_platform.IS_ESP32_S3 = original_is_esp32_s3
            hardware_platform.esp32 = original_esp32

        self.assertFalse(capability['supported'])
        self.assertIn('no inactive OTA partition', capability['reason'])
        self.assertEqual(capability['running_partition'], 'factory')

    def test_firmware_ota_maps_enoent_to_missing_inactive_partition(self):
        class RunningPartition:
            def info(self):
                return (0, 0, 0, 0x200000, 'factory', False)

            def get_next_update(self):
                raise OSError(2, 'ENOENT')

        class Esp32:
            class Partition:
                RUNNING = 1

                def __new__(cls, identifier):
                    return RunningPartition()

        original_is_esp32_s3 = hardware_platform.IS_ESP32_S3
        original_esp32 = hardware_platform.esp32
        try:
            hardware_platform.IS_ESP32_S3 = True
            hardware_platform.esp32 = Esp32
            capability = hardware_platform.firmware_ota_capability()
        finally:
            hardware_platform.IS_ESP32_S3 = original_is_esp32_s3
            hardware_platform.esp32 = original_esp32

        self.assertFalse(capability['supported'])
        self.assertIn('no inactive OTA partition', capability['reason'])
        self.assertNotIn('ENOENT', capability['reason'])

    def test_firmware_ota_reports_target_partition(self):
        class TargetPartition:
            def info(self):
                return (0, 0, 0, 0x200000, 'ota_1', False)

        class RunningPartition:
            def info(self):
                return (0, 0, 0, 0x200000, 'ota_0', False)

            def get_next_update(self):
                return TargetPartition()

        class Esp32:
            class Partition:
                RUNNING = 1

                def __new__(cls, identifier):
                    return RunningPartition()

        original_is_esp32_s3 = hardware_platform.IS_ESP32_S3
        original_esp32 = hardware_platform.esp32
        try:
            hardware_platform.IS_ESP32_S3 = True
            hardware_platform.esp32 = Esp32
            capability = hardware_platform.firmware_ota_capability()
        finally:
            hardware_platform.IS_ESP32_S3 = original_is_esp32_s3
            hardware_platform.esp32 = original_esp32

        self.assertTrue(capability['supported'])
        self.assertEqual(capability['running_partition'], 'ota_0')
        self.assertEqual(capability['target_partition'], 'ota_1')

    def test_null_output_is_pin_compatible(self):
        output = hardware_platform.NullOutput()
        self.assertEqual(output(), 0)
        output(1)
        self.assertEqual(output(), 1)
        output.toggle()
        self.assertEqual(output(), 0)

    def test_esp32_watchdog_timeout_is_not_artificially_capped(self):
        self.assertEqual(hardware_platform.watchdog_timeout(15000), 15000)
        self.assertEqual(hardware_platform.watchdog_timeout(0), 0)

    def test_unsupported_runtime_is_reported_explicitly(self):
        original = hardware_platform.IS_ESP32_S3
        try:
            hardware_platform.IS_ESP32_S3 = False
            self.assertEqual(hardware_platform.platform_id(), 'unsupported')
            capability = hardware_platform.firmware_ota_capability()
        finally:
            hardware_platform.IS_ESP32_S3 = original

        self.assertFalse(capability['supported'])
        self.assertIn('ESP32-S3', capability['reason'])

    def test_neopixel_output_is_boolean_compatible(self):
        class Pixel:
            def __init__(self):
                self.colour = None
                self.writes = 0

            def __setitem__(self, index, colour):
                self.colour = colour

            def write(self):
                self.writes += 1

        pixel = Pixel()
        output = hardware_platform.NeoPixelOutput(pixel)

        self.assertEqual(output(), 0)
        self.assertEqual(pixel.colour, (0, 0, 0))
        output(1)
        self.assertEqual(output(), 1)
        self.assertEqual(pixel.colour, (16, 0, 0))
        output.toggle()
        self.assertEqual(output(), 0)
        self.assertEqual(pixel.colour, (0, 0, 0))

    def test_neopixel_colour_can_change_while_on(self):
        class Pixel:
            def __init__(self):
                self.colour = None

            def __setitem__(self, index, colour):
                self.colour = colour

            def write(self):
                pass

        pixel = Pixel()
        output = hardware_platform.NeoPixelOutput(pixel)
        output(1)
        output.set_colour(hardware_platform.STATUS_COLOUR_WARNING)

        self.assertEqual(pixel.colour, (16, 16, 0))
        self.assertEqual(output(), 1)

    def test_status_led_colours_are_distinct(self):
        self.assertEqual(hardware_platform.STATUS_COLOUR_OK, (16, 0, 0))
        self.assertEqual(hardware_platform.STATUS_COLOUR_WARNING, (16, 16, 0))
        self.assertEqual(hardware_platform.STATUS_COLOUR_ERROR, (0, 16, 0))

    def test_status_led_mode_prioritises_main_errors(self):
        self.assertEqual(
            hardware_platform.status_led_mode(False, False),
            (hardware_platform.STATUS_COLOUR_OK, False)
        )
        self.assertEqual(
            hardware_platform.status_led_mode(False, True),
            (hardware_platform.STATUS_COLOUR_WARNING, False)
        )
        self.assertEqual(
            hardware_platform.status_led_mode(True, True),
            (hardware_platform.STATUS_COLOUR_ERROR, True)
        )
