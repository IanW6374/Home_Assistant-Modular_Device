import importlib
import json
import sys
import types
import unittest


class FakePin:
    OUT = 1

    def __init__(self, value=None, mode=None):
        self.value_arg = value
        self.mode = mode
        self.state = 1

    def value(self, state=None):
        if state is None:
            return self.state
        self.state = state


class FakeSPI:
    MSB = 0

    def __init__(self):
        self.registers = {
            0x00: 0,
            0x01: 0,
            0x02: 0,
            0x07: 0
        }
        self.current_register = 0
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))
        if len(data) == 1:
            self.current_register = data[0] & 0x7f
        elif len(data) >= 2:
            self.registers[data[0] & 0x7f] = data[1]

    def read(self, count):
        data = []
        for offset in range(count):
            data.append(self.registers.get(self.current_register + offset, 0))
        return bytes(data)

    def set_rtd_raw(self, raw):
        encoded = raw << 1
        self.registers[0x01] = (encoded >> 8) & 0xff
        self.registers[0x02] = encoded & 0xff


def load_module():
    machine = types.ModuleType('machine')
    machine.Pin = FakePin
    machine.SPI = lambda *args, **kwargs: FakeSPI()
    machine.SPI.MSB = FakeSPI.MSB
    sys.modules['machine'] = machine

    sys.modules.pop('device_modules.max31865_pt1000', None)
    sys.modules.pop('device_modules.spi_bus', None)
    return importlib.import_module('device_modules.max31865_pt1000')


def device_config():
    return {
        'name': 'PT1000',
        'uuid': '0001',
        'type': {'class': 'sensor', 'subclass': 'MAX31865-PT1000'},
        'max31865': {
            'auto_convert': True,
            'rtd_nominal': 1000,
            'ref_resistor': 4300,
            'wires': 3,
            'filter_hz': 50,
            'precision': 2
        },
        'entities': {
            '0': {'class': 'temperature', 'key': 'temperature', 'value': None},
            '1': {'class': 'memory_value', 'key': 'resistance', 'value': None},
            '2': {'class': 'memory_value', 'key': 'rtd_raw', 'value': None},
            '3': {'class': 'memory_value', 'key': 'fault', 'value': ''},
            '4': {'class': 'memory_value', 'key': 'fault_code', 'value': 0}
        }
    }


class MAX31865PT1000Tests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.spi = FakeSPI()
        self.cs = FakePin(5, FakePin.OUT)
        self.driver = self.module.MAX31865PT1000Driver(
            device_config(),
            {'spi': self.spi, 'cs': self.cs}
        )

    def raw_for_resistance(self, resistance):
        return int(round((resistance / 4300.0) * 32768))

    def test_configure_uses_3wire_50hz_auto_convert(self):
        self.driver._configure()

        self.assertEqual(
            self.spi.registers[0x00],
            self.module.CONFIG_BIAS |
            self.module.CONFIG_AUTO_CONVERT |
            self.module.CONFIG_3WIRE |
            self.module.CONFIG_FAULT_CLEAR |
            self.module.CONFIG_FILTER_50HZ
        )

    def test_reads_near_zero_celsius_from_pt1000_resistance(self):
        self.spi.set_rtd_raw(self.raw_for_resistance(1000.0))

        reading = self.driver.read()

        self.assertAlmostEqual(reading['temperature'], 0, delta=0.1)
        self.assertAlmostEqual(reading['resistance'], 1000, delta=0.1)
        self.assertEqual(reading['fault'], '')

    def test_reads_near_100_celsius_from_pt1000_resistance(self):
        resistance_100c = 1000.0 * (1 + (self.module.RTD_A * 100) + (self.module.RTD_B * 100 * 100))
        self.spi.set_rtd_raw(self.raw_for_resistance(resistance_100c))

        reading = self.driver.read()

        self.assertAlmostEqual(reading['temperature'], 100, delta=0.1)

    def test_fault_status_is_exposed(self):
        self.spi.set_rtd_raw(self.raw_for_resistance(1000.0))
        self.spi.registers[0x07] = 0x80

        reading = self.driver.read()

        self.assertEqual(reading['fault_code'], 0x80)
        self.assertEqual(reading['fault'], 'RTD high threshold')

    def test_updates_configured_entities(self):
        self.spi.set_rtd_raw(self.raw_for_resistance(1000.0))

        self.driver._update_entities(self.driver.read())
        payload = self.driver.get_state_payload()

        self.assertAlmostEqual(payload['temperature'], 0, delta=0.1)
        self.assertAlmostEqual(payload['resistance'], 1000, delta=0.1)
        self.assertIsInstance(payload['rtd_raw'], int)

    def test_discovery_payload_uses_entity_keys(self):
        discovery, payload = self.driver.get_discovery_payloads('abc', 'Pico Temperature')

        self.assertIn('temperature', discovery)
        self.assertEqual(discovery['temperature']['uniq_id'], 'abc0001_temperature')
        self.assertEqual(discovery['temperature']['dev']['name'], 'Pico Temperature')
        self.assertIn('temperature', payload)

    def test_setup_creates_spi_and_cs(self):
        device = device_config()
        device['max31865'].update({'spi': 1, 'sck': 10, 'mosi': 11, 'miso': 12, 'cs': 13})

        device_char = self.module.setup(device, 2)

        self.assertEqual(device_char['uuid'], '0001')
        self.assertEqual(device_char['index'], 2)
        self.assertIn('spi', device_char)
        self.assertEqual(device_char['cs'].state, 1)

    def test_setup_reuses_matching_spi_bus(self):
        first = device_config()
        second = device_config()
        second['uuid'] = '0002'
        second['max31865']['cs'] = 6

        first_char = self.module.setup(first, 1)
        second_char = self.module.setup(second, 2)

        self.assertIs(first_char['spi'], second_char['spi'])

    def test_setup_rejects_conflicting_spi_bus(self):
        first = device_config()
        second = device_config()
        second['uuid'] = '0002'
        second['max31865'].update({'phase': 0, 'cs': 6})

        self.module.setup(first, 1)

        with self.assertRaisesRegex(RuntimeError, 'different pins or mode'):
            self.module.setup(second, 2)

    def test_example_config_validates(self):
        from device_modules.validation import validate_device_config

        with open('examples/module_settings.max31865_pt1000.example.json', 'rb') as f:
            config = json.loads(f.read())

        self.assertEqual(validate_device_config(config, [self.module.DEVICE_TYPE]), [])

    def test_dual_pt1000_voltage_display_example_validates(self):
        from device_modules import grove_ac_voltage
        from device_modules.validation import validate_device_config

        with open('examples/module_settings.dual_pt1000_voltage_display.example.json', 'rb') as f:
            config = json.loads(f.read())

        errors = validate_device_config(
            config,
            [self.module.DEVICE_TYPE, grove_ac_voltage.DEVICE_TYPE]
        )
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
