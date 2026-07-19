import importlib
import sys
import types
import unittest


class FakePin:
    OUT = 1

    def __init__(self, number, mode=None):
        self.number = number
        self.mode = mode
        self.state = None

    def value(self, state=None):
        if state is None:
            return self.state
        self.state = state


class FakeUART:
    def __init__(self, uart, **config):
        self.uart = uart
        self.config = config


def load_module():
    machine = types.ModuleType('machine')
    machine.Pin = FakePin
    machine.UART = FakeUART
    sys.modules['machine'] = machine
    sys.modules.pop('device_modules.rs485_modbus', None)
    return importlib.import_module('device_modules.rs485_modbus')


class RS485ModbusTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_setup_creates_one_ch0_port_from_flat_config(self):
        device = {
            'uuid': '0001',
            'rs485': {
                'uart': 1,
                'tx': 17,
                'rx': 18,
                'de': 16,
                'baudrate': 115200,
                'timeout_ms': 750
            }
        }

        device_char = self.module.setup(device, 0)

        self.assertEqual(list(device_char['ports']), ['ch0'])
        port = device_char['ports']['ch0']
        self.assertEqual(port['uart'].uart, 1)
        self.assertEqual(port['uart'].config['tx'].number, 17)
        self.assertEqual(port['uart'].config['rx'].number, 18)
        self.assertEqual(port['timeout_ms'], 750)
        self.assertEqual(port['tx_enable'].number, 16)
        self.assertEqual(port['tx_enable'].state, 0)

    def test_whes_device_uses_same_single_port_setup(self):
        device = {
            'uuid': '0002',
            'type': {'class': 'sensor', 'subclass': 'WHES'},
            'rs485': {'uart': 1, 'tx': 17, 'rx': 18, 'baudrate': 115200}
        }

        device_char = self.module.setup(device, 0)

        self.assertEqual(list(device_char['ports']), ['ch0'])


if __name__ == '__main__':
    unittest.main()
