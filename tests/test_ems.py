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
            '7': {'class': 'memory_value', 'key': 'ems_frames', 'value': 0}
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
        self.assertTrue(payload['tapwateractive'])
        self.assertEqual(payload['servicecode'], '--')
        self.assertEqual(payload['ems_frames'], 1)

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

    def test_rejects_bad_crc(self):
        frame = self.with_crc([0x08, 0x00, 0x18, 0x00, 0x37, 0x01, 0xf4])
        frame = frame[:-1] + bytes([frame[-1] ^ 0xff])

        self.assertFalse(self.driver._process_frame(frame))
        payload = self.driver.get_state_payload()

        self.assertEqual(payload['ems_frames'], 0)
        self.assertEqual(self.driver._diagnostics['ems_crc_errors'], 1)

    def test_discovery_uses_configured_entities(self):
        discovery, payload = self.driver.get_discovery_payloads('abc', 'Heating Pico')

        self.assertIn('curflowtemp', discovery)
        self.assertEqual(discovery['curflowtemp']['uniq_id'], 'abc0001_curflowtemp')
        self.assertEqual(discovery['curflowtemp']['dev']['name'], 'Heating Pico')
        self.assertIn('curflowtemp', payload)

    def test_example_config_validates(self):
        from device_modules.validation import validate_device_config

        with open('examples/module_settings.ems.example.json', 'rb') as f:
            config = json.loads(f.read())

        self.assertEqual(validate_device_config(config, [self.ems.DEVICE_TYPE]), [])


if __name__ == '__main__':
    unittest.main()
