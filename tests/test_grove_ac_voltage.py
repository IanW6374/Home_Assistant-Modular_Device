import importlib
import json
import sys
import types
import unittest


class FakePin:
    def __init__(self, value=None, mode=None):
        self.value_arg = value
        self.mode = mode


class FakeADC:
    def __init__(self, pin=None):
        self.pin = pin
        self.values = [32768]
        self.index = 0

    def read_u16(self):
        value = self.values[self.index % len(self.values)]
        self.index += 1
        return value


def load_module(adc_holder):
    machine = types.ModuleType('machine')
    machine.Pin = FakePin

    def adc_factory(pin):
        adc = FakeADC(pin)
        adc_holder.append(adc)
        return adc

    machine.ADC = adc_factory
    sys.modules['machine'] = machine

    sys.modules.pop('device_modules.grove_ac_voltage', None)
    return importlib.import_module('device_modules.grove_ac_voltage')


def device_config():
    return {
        'name': 'AC Voltage',
        'uuid': '0001',
        'type': {'class': 'sensor', 'subclass': 'Grove-AC-Voltage'},
        'pollinterval': 5,
        'ac_voltage': {
            'adc_pin': 26,
            'vref': 3.3,
            'adc_max': 65535,
            'sample_count': 4,
            'sample_delay_us': 0,
            'calibration': 1000,
            'threshold': 40,
            'hysteresis': 5,
            'threshold_key': 'ac_present'
        },
        'entities': {
            '0': {'class': 'voltage', 'key': 'voltage', 'value': None, 'unit': 'V'},
            '1': {
                'class': 'memory_value',
                'key': 'ac_present',
                'value': False,
                'component': 'binary_sensor',
                'device_class': 'power'
            },
            '2': {'class': 'memory_value', 'key': 'adc_rms', 'value': None},
            '3': {'class': 'memory_value', 'key': 'adc_midpoint', 'value': None}
        }
    }


class GroveACVoltageTests(unittest.TestCase):
    def setUp(self):
        self.adcs = []
        self.module = load_module(self.adcs)
        self.adc = FakeADC()
        self.driver = self.module.GroveACVoltageDriver(
            device_config(),
            {'adc': self.adc}
        )

    def test_setup_creates_adc_from_configured_pin(self):
        device_char = self.module.setup(device_config(), 3)

        self.assertEqual(device_char['uuid'], '0001')
        self.assertEqual(device_char['index'], 3)
        self.assertEqual(self.adcs[0].pin.value_arg, 26)

    def test_reads_rms_voltage_from_centered_waveform(self):
        self.adc.values = [33768, 31768, 33768, 31768]

        reading = self.driver.read()

        self.assertAlmostEqual(reading['adc_midpoint'], 32768, delta=0.01)
        self.assertAlmostEqual(reading['adc_rms'], 1000, delta=0.01)
        self.assertAlmostEqual(reading['voltage'], 50.4, delta=0.1)
        self.assertTrue(reading['ac_present'])

    def test_threshold_hysteresis_prevents_chatter(self):
        self.adc.values = [33768, 31768, 33768, 31768]
        self.assertTrue(self.driver.read()['ac_present'])

        self.adc.values = [33568, 31968, 33568, 31968]
        self.assertTrue(self.driver.read()['ac_present'])

        self.adc.values = [33400, 32136, 33400, 32136]
        self.assertFalse(self.driver.read()['ac_present'])

    def test_updates_configured_entities(self):
        self.adc.values = [33768, 31768, 33768, 31768]

        self.driver._update_entities(self.driver.read())
        payload = self.driver.get_state_payload()

        self.assertAlmostEqual(payload['voltage'], 50.4, delta=0.1)
        self.assertTrue(payload['ac_present'])
        self.assertEqual(payload['adc_rms'], 1000)

    def test_runtime_calibration_uses_current_voltage(self):
        self.driver._update_entities({'voltage': 50})

        result = self.driver.set_calibration({'known_voltage': '100'})

        self.assertTrue(result['ok'])
        self.assertEqual(result['calibration'], 2000)
        self.assertEqual(self.driver.device['ac_voltage']['calibration'], 2000)

    def test_binary_discovery_uses_binary_sensor_component(self):
        discovery, _ = self.driver.get_discovery_payloads('abc', 'Voltage Monitor')

        self.assertEqual(discovery['ac_present']['_component'], 'binary_sensor')
        self.assertEqual(discovery['ac_present']['device_class'], 'power')
        self.assertEqual(discovery['ac_present']['payload_on'], 'ON')
        self.assertEqual(discovery['ac_present']['payload_off'], 'OFF')
        self.assertEqual(discovery['ac_present']['uniq_id'], 'abc0001_ac_present')

    def test_example_config_validates(self):
        from device_modules.validation import validate_device_config

        with open('examples/module_settings.grove_ac_voltage.example.json', 'rb') as f:
            config = json.loads(f.read())

        self.assertEqual(validate_device_config(config, [self.module.DEVICE_TYPE]), [])


if __name__ == '__main__':
    unittest.main()
