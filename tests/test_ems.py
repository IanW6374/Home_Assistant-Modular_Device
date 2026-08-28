import importlib
import json
import sys
import types
import unittest


class FakePin:
    def __init__(self, value=None, mode=None):
        self.value_arg = value
        self.mode = mode


class FakeUART:
    def __init__(self):
        self.reply = b''

    def any(self):
        return len(self.reply)

    def read(self, size=None):
        if size is None:
            size = len(self.reply)
        chunk = self.reply[:size]
        self.reply = self.reply[size:]
        return chunk


class FakeBreakUART(FakeUART):
    IRQ_BREAK = 4

    def __init__(self):
        super().__init__()
        self.irq_handler = None
        self.irq_trigger = None

    def irq(self, handler=None, trigger=0):
        self.irq_handler = handler
        self.irq_trigger = trigger
        return self

    def fire_break(self):
        self.irq_handler(self)


def load_module():
    machine = types.ModuleType('machine')
    machine.Pin = FakePin
    machine.UART = lambda *args, **kwargs: FakeUART()
    sys.modules['machine'] = machine

    sys.modules.pop('device_modules.ems', None)
    return importlib.import_module('device_modules.ems')


def ems_device(entities=None):
    if entities is None:
        entities = {
            '0': {'class': 'temperature', 'key': 'curflowtemp', 'value': None},
            '1': {'class': 'temperature', 'key': 'rettemp', 'value': None},
            '2': {'class': 'pressure', 'key': 'syspress', 'value': None},
            '3': {'class': 'memory_value', 'key': 'curburnpow', 'value': None},
            '4': {'class': 'memory_value', 'key': 'burngas', 'value': False},
            '5': {'class': 'memory_value', 'key': 'tapwateractive', 'value': False},
            '6': {'class': 'memory_value', 'key': 'servicecode', 'value': ''},
            '7': {'class': 'memory_value', 'key': 'ems_frames', 'value': 0},
            '8': {'class': 'memory_value', 'key': 'flameactive', 'value': False}
        }
    return {
        'name': 'Greenstar 8000',
        'uuid': '0001',
        'type': {'class': 'sensor', 'subclass': 'EMS-Boiler'},
        'entities': entities
    }


class EMSTests(unittest.TestCase):
    def setUp(self):
        self.ems = load_module()
        self.driver = self.ems.EMSBoilerDriver(ems_device(), {'uart': FakeUART()})

    def with_crc(self, data):
        return bytes(data + [self.driver._crc(bytes(data))])

    def test_crc_is_stable_for_ems_plus_sample(self):
        frame_without_crc = bytes([
            0x88, 0x00, 0xE4, 0x00, 0x00, 0x2D, 0x2D, 0x00,
            0x00, 0xC9, 0x34, 0x02, 0x21, 0x64, 0x3D, 0x05,
            0x02, 0x01, 0xDE, 0x00, 0x00, 0x00, 0x00, 0x03,
            0x62, 0x14, 0x00, 0x02, 0x21, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x2B, 0x2B
        ])

        self.assertEqual(self.driver._crc(frame_without_crc), 0xA5)

    def test_break_irq_removes_esp32_break_byte_before_crc(self):
        uart = FakeBreakUART()
        driver = self.ems.EMSBoilerDriver(ems_device(), {'uart': uart})
        frame = bytes([
            0x88, 0x00, 0xE5, 0x1C, 0x00, 0x00, 0x00, 0x00, 0x2E
        ])
        self.assertEqual(driver._crc(frame[:-1]), frame[-1])

        self.assertTrue(driver._enable_break_irq(uart))
        uart.reply = frame + b'\x00'
        uart.fire_break()

        self.assertEqual(driver._rx_frames, [frame])
        self.assertEqual(driver._diagnostics['ems_breaks'], 1)
        self.assertEqual(driver._rx_buffer, bytearray())

    def test_idle_fallback_removes_valid_trailing_break_byte(self):
        frame = self.with_crc([0x88, 0x00, 0xE5, 0x1C, 0, 0, 0, 0])
        self.driver._rx_buffer.extend(frame + b'\x00')

        self.driver._queue_idle_buffer()

        self.assertEqual(self.driver._rx_frames, [frame])

    def test_senses_ems_plus_and_ht3_addressing_from_valid_frame(self):
        frame = self.with_crc([0x88, 0x00, 0xE4, 0x00, 0, 0, 0, 0])

        self.driver._process_frame(frame)

        self.assertEqual(
            self.driver._diagnostics['ems_bus_protocol'],
            'EMS+ (HT3/Junkers)'
        )

    def test_parses_ems_plus_extended_type_using_ems_esp_numbering(self):
        frame = self.with_crc([
            0x08, 0x00, 0xFF, 0x00, 0x03, 0x95, 0x00
        ])

        telegram = self.driver._parse_telegram(frame)

        self.assertEqual(telegram['type'], 0x495)

    def test_decodes_monitor_fragment_at_nonzero_offset(self):
        entities = {
            '0': {'class': 'memory_value', 'key': 'pc0flow', 'value': None}
        }
        driver = self.ems.EMSBoilerDriver(
            ems_device(entities), {'uart': FakeUART()}
        )
        # E4 fragment begins at offset 35; pc0flow is the signed word at 36.
        frame = bytes([0x88, 0x00, 0xE4, 0x23, 0x00, 0x09, 0x60, 0x00])
        frame += bytes([driver._crc(frame)])

        self.assertTrue(driver._process_frame(frame))
        self.assertEqual(driver.get_state_payload()['pc0flow'], 2400)

    def test_fragment_does_not_decode_value_crossing_its_start(self):
        entities = {
            '0': {'class': 'temperature', 'key': 'exhausttemp', 'value': None}
        }
        driver = self.ems.EMSBoilerDriver(
            ems_device(entities), {'uart': FakeUART()}
        )
        # Exhaust temperature starts at 31, before this fragment's offset 32.
        frame = bytes([0x88, 0x00, 0xE4, 0x20, 0x20, 0x00, 0x00])
        frame += bytes([driver._crc(frame)])

        self.assertFalse(driver._process_frame(frame))
        self.assertIsNone(driver.get_state_payload()['exhausttemp'])

    def test_setup_defaults_to_safe_esp32_s3_uart1_pins(self):
        captured = {}

        def uart_factory(number, **config):
            captured['number'] = number
            captured['config'] = config
            return FakeUART()

        self.ems.UART = uart_factory
        result = self.ems.setup(ems_device(), 1)

        self.assertEqual(captured['number'], 1)
        self.assertEqual(captured['config']['tx'].value_arg, 17)
        self.assertEqual(captured['config']['rx'].value_arg, 18)
        self.assertIn('driver', result)

    def test_decodes_ems_plus_fast_monitor(self):
        frame_without_crc = [
            0x88, 0x00, 0xE4, 0x00, 0x00, 0x2D, 0x2D, 0x00,
            0x00, 0xC9, 0x34, 0x02, 0x21, 0x64, 0x3D, 0x05,
            0x02, 0x01, 0xDE, 0x00, 0x00, 0x00, 0x00, 0x03,
            0x62, 0x14, 0x00, 0x02, 0x21, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x2B, 0x2B
        ]
        frame = self.with_crc(frame_without_crc)

        self.assertTrue(self.driver._process_frame(frame))
        payload = self.driver.get_state_payload()

        self.assertEqual(payload['curflowtemp'], 54.5)
        self.assertIsNone(payload['rettemp'])
        self.assertEqual(payload['syspress'], 2)
        self.assertEqual(payload['curburnpow'], 61)
        self.assertTrue(payload['burngas'])
        self.assertTrue(payload['flameactive'])
        self.assertTrue(payload['tapwateractive'])
        self.assertEqual(payload['servicecode'], '--')
        self.assertEqual(payload['ems_frames'], 1)
        self.assertTrue(self.driver.diagnostics_payload()['last_ok'])
        self.assertEqual(
            self.driver.diagnostics_payload()['consecutive_errors'],
            0
        )

    def test_decodes_classic_fast_monitor(self):
        data = bytearray(24)
        data[0] = 55
        data[1:3] = b'\x01\xf4'
        data[3] = 80
        data[4] = 40
        data[5] = 0x0b
        data[7] = 0x21
        data[13:15] = b'\x01\x2c'
        data[15:17] = b'\x00\x15'
        data[17] = 0x13
        data[18:20] = b'H1'
        data[20:22] = b'\x12\x34'
        frame = self.with_crc([0x08, 0x00, 0x18, 0x00] + list(data))

        self.assertTrue(self.driver._process_frame(frame))
        payload = self.driver.get_state_payload()

        self.assertEqual(payload['curflowtemp'], 50)
        self.assertEqual(payload['rettemp'], 30)
        self.assertEqual(payload['syspress'], 1.9)
        self.assertEqual(payload['curburnpow'], 40)
        self.assertTrue(payload['burngas'])
        self.assertTrue(payload['tapwateractive'])
        self.assertEqual(payload['servicecode'], 'H1')

    def test_ems_plus_clears_flameactive_when_burner_stops(self):
        active_data = bytearray(22)
        active_data[11] = 0x01
        active = self.with_crc(
            [0x88, 0x00, 0xE4, 0x00] + list(active_data)
        )
        inactive_data = bytearray(22)
        inactive = self.with_crc(
            [0x88, 0x00, 0xE4, 0x00] + list(inactive_data)
        )

        self.assertTrue(self.driver._process_frame(active))
        self.assertTrue(self.driver.get_state_payload()['flameactive'])
        self.assertTrue(self.driver._process_frame(inactive))
        self.assertFalse(self.driver.get_state_payload()['flameactive'])

    def test_rejects_bad_crc(self):
        frame = self.with_crc([0x08, 0x00, 0x18, 0x00, 0x37, 0x01, 0xf4])
        frame = frame[:-1] + bytes([frame[-1] ^ 0xff])

        self.assertFalse(self.driver._process_frame(frame))
        payload = self.driver.get_state_payload()

        self.assertEqual(payload['ems_frames'], 0)
        self.assertEqual(self.driver._diagnostics['ems_crc_errors'], 1)
        self.assertFalse(self.driver.diagnostics_payload()['last_ok'])
        self.assertEqual(
            self.driver.diagnostics_payload()['last_error'],
            'crc mismatch'
        )

    def test_valid_frame_clears_module_health_error(self):
        bad_frame = self.with_crc([
            0x08, 0x00, 0x18, 0x00, 0x37, 0x01, 0xf4
        ])
        bad_frame = bad_frame[:-1] + bytes([bad_frame[-1] ^ 0xff])
        self.driver._process_frame(bad_frame)

        data = bytearray(24)
        data[0] = 55
        good_frame = self.with_crc(
            [0x08, 0x00, 0x18, 0x00] + list(data)
        )
        self.driver._process_frame(good_frame)

        health = self.driver.diagnostics_payload()
        self.assertTrue(health['last_ok'])
        self.assertEqual(health['last_error'], '')
        self.assertEqual(health['consecutive_errors'], 0)

    def test_poll_traffic_is_not_counted_as_crc_error(self):
        poll_traffic = bytes([0x89, 0x08, 0x88, 0x08, 0x88, 0x17, 0x09])

        self.assertFalse(self.driver._process_frame(poll_traffic))
        self.assertEqual(self.driver._diagnostics['ems_crc_errors'], 0)

    def test_boiler_poll_sequence_is_not_counted_as_crc_error(self):
        poll_traffic = bytes([0x88, 0x09, 0x89, 0x10, 0x08, 0x88])

        self.assertFalse(self.driver._process_frame(poll_traffic))
        self.assertEqual(self.driver._diagnostics['ems_crc_errors'], 0)

    def test_debug_frames_identifies_bus_activity(self):
        device = ems_device()
        device['ems'] = {'debug_frames': True}
        driver = self.ems.EMSBoilerDriver(device, {'uart': FakeUART()})
        messages = []
        driver._log_callable = lambda mode, action, data, level: messages.append(
            data['log']
        )

        self.assertFalse(driver._process_frame(
            bytes([0x89, 0x08, 0x88, 0x08, 0x88, 0x17, 0x09])
        ))
        self.assertIn('rx bus activity', messages[0])
        self.assertEqual(driver._diagnostics['ems_crc_errors'], 0)

    def test_debug_frames_logs_bad_frame_details(self):
        device = ems_device()
        device['ems'] = {'debug_frames': True}
        driver = self.ems.EMSBoilerDriver(device, {'uart': FakeUART()})
        messages = []
        driver._log_callable = lambda mode, action, data, level: messages.append(
            (data['log'], level)
        )
        frame = bytes([0x08, 0x00, 0x18, 0x00, 0x37, 0x00])

        self.assertFalse(driver._process_frame(frame))
        self.assertEqual(len(messages), 1)
        self.assertIn('rx crc mismatch expected=', messages[0][0])
        self.assertIn('received=0x00', messages[0][0])
        self.assertIn(
            'len=6 data=0x08 0x00 0x18 0x00 0x37 0x00',
            messages[0][0]
        )
        self.assertEqual(messages[0][1], 'INFO')

    def test_debug_frames_logs_short_buffer(self):
        device = ems_device()
        device['ems'] = {'debug_frames': True}
        driver = self.ems.EMSBoilerDriver(device, {'uart': FakeUART()})
        messages = []
        driver._log_callable = lambda mode, action, data, level: messages.append(
            data['log']
        )

        self.assertFalse(driver._process_frame(bytes([0x08])))
        self.assertEqual(messages, ['rx short len=1 data=0x08'])

    def test_debug_frames_can_be_toggled_at_runtime(self):
        driver = self.ems.EMSBoilerDriver(ems_device(), {'uart': FakeUART()})
        messages = []
        driver._log_callable = lambda mode, action, data, level: messages.append(
            data['log']
        )

        self.assertFalse(driver.debug_frames_enabled())
        self.assertTrue(driver.set_debug_frames(True))
        driver._process_frame(bytes([0x08]))
        self.assertEqual(messages, ['rx short len=1 data=0x08'])
        self.assertFalse(driver.set_debug_frames(False))
        driver._process_frame(bytes([0x09]))
        self.assertEqual(messages, ['rx short len=1 data=0x08'])

    def test_discovery_uses_configured_entities(self):
        discovery, payload = self.driver.get_discovery_payloads('abc', 'Heating Controller')

        self.assertIn('curflowtemp', discovery)
        self.assertEqual(discovery['curflowtemp']['uniq_id'], 'abc0001_curflowtemp')
        self.assertEqual(discovery['curflowtemp']['dev']['name'], 'Heating Controller')
        self.assertIn('curflowtemp', payload)

    def test_example_config_validates(self):
        from device_modules.validation import validate_device_config

        with open('examples/module_settings.ems.example.json', 'rb') as f:
            config = json.loads(f.read())

        self.assertEqual(validate_device_config(config, [self.ems.DEVICE_TYPE]), [])

    def test_validation_rejects_console_uart_and_reserved_pins(self):
        from device_modules.validation import validate_device_config

        with open('examples/module_settings.ems.json', 'rb') as stream:
            config = json.loads(stream.read())

        config['devices'][0]['ems'].update({'uart': 0, 'tx': 38, 'rx': 38})
        errors = validate_device_config(config, [self.ems.DEVICE_TYPE])
        joined = '; '.join(errors)

        self.assertIn('UART0 is reserved for the console', joined)
        self.assertIn('GPIO38 is reserved for the IoT-MD status LED', joined)
        self.assertIn('GPIO38 is already used by ems.tx', joined)


if __name__ == '__main__':
    unittest.main()
