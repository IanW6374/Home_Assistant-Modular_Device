import asyncio
import importlib
import sys
import time
import types
import unittest


async def sleep_ms(_):
    await asyncio.sleep(0)


class FakePin:
    OUT = 1

    def __init__(self, value=None, mode=None):
        self.value_arg = value
        self.mode = mode
        self.state = 0

    def value(self, state=None):
        if state is None:
            return self.state
        self.state = state


class FakeUART:
    def __init__(self):
        self.writes = []
        self.reply = b''

    def any(self):
        return len(self.reply)

    def read(self, size=None):
        if size is None:
            size = len(self.reply)
        chunk = self.reply[:size]
        self.reply = self.reply[size:]
        return chunk

    def write(self, data):
        self.writes.append(data)
        function = data[1]
        if function == 6:
            self.reply = data
        elif function == 16:
            body = data[:6]
            self.reply = body + PicoModuleTest.driver._crc_bytes(body)

    def flush(self):
        pass


def load_module():
    machine = types.ModuleType('machine')
    machine.Pin = FakePin
    machine.UART = lambda *args, **kwargs: FakeUART()
    sys.modules['machine'] = machine

    if not hasattr(asyncio, 'sleep_ms'):
        asyncio.sleep_ms = sleep_ms

    sys.modules.pop('device_modules.pico_2ch_rs485', None)
    module = importlib.import_module('device_modules.pico_2ch_rs485')
    module.time.ticks_ms = lambda: int(time.monotonic() * 1000)
    module.time.ticks_add = lambda ticks, delta: ticks + delta
    module.time.ticks_diff = lambda end, start: end - start
    return module


class PicoModuleTest(unittest.TestCase):
    driver = None

    def setUp(self):
        self.module = load_module()
        self.uart = FakeUART()
        device = {
            'name': 'RS485',
            'uuid': '0002',
            'type': {'class': 'sensor', 'subclass': 'Pico-2CH-RS485'},
            'entities': {}
        }
        devchar = {
            'ports': {
                'ch0': {
                    'uart': self.uart,
                    'tx_enable': None,
                    'turnaround_ms': 0,
                    'timeout_ms': 100
                }
            }
        }
        PicoModuleTest.driver = self.module.Pico2CHRS485Driver(device, devchar)
        self.driver = PicoModuleTest.driver

    def test_write_request_uses_function_6_for_single_register(self):
        response = asyncio.run(self.driver._write_request({
            'operation': 'write',
            'port': 'ch0',
            'slave': 1,
            'address': 60009,
            'value': 20,
            'data_type': 'uint16',
            'scale': 0.01
        }))

        self.assertTrue(response['ok'])
        self.assertEqual(response['function'], 6)
        self.assertEqual(response['count'], 1)
        self.assertEqual(response['raw'], '07d0')
        self.assertEqual(self.uart.writes[0][:6], b'\x01\x06\xeai\x07\xd0')

    def test_write_request_uses_function_16_for_multiple_registers(self):
        response = asyncio.run(self.driver._write_request({
            'operation': 'write',
            'port': 'ch0',
            'slave': 1,
            'address': 100,
            'values': [1, 2],
            'data_type': 'uint16'
        }))

        self.assertTrue(response['ok'])
        self.assertEqual(response['function'], 16)
        self.assertEqual(response['count'], 2)
        self.assertEqual(response['raw'], '00010002')
        self.assertEqual(
            self.uart.writes[0][:9],
            b'\x01\x10\x00d\x00\x02\x04\x00\x01'
        )

    def test_request_operation_defaults_to_read_without_values(self):
        self.assertFalse(self.driver._is_write_request({'operation': 'read'}))
        self.assertFalse(self.driver._is_write_request({'address': 1}))
        self.assertTrue(self.driver._is_write_request({'address': 1, 'value': 2}))

    def test_function_accepts_whes_x10_notation(self):
        response = asyncio.run(self.driver._write_request({
            'operation': 'write',
            'port': 'ch0',
            'slave': 1,
            'address': 60009,
            'function': 'x10',
            'values': [20],
            'data_type': 'uint16',
            'scale': 0.01
        }))

        self.assertTrue(response['ok'])
        self.assertEqual(response['function'], 16)
        self.assertEqual(self.uart.writes[0][1], 0x10)


if __name__ == '__main__':
    unittest.main()
