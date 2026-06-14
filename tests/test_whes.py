import importlib.util
import sys
import types
import unittest


def load_whes_module():
    rs485 = types.ModuleType('device_modules.pico_2ch_rs485')

    class Base:
        def __init__(self, device, device_char):
            self.device = device
            self.devchar = device_char

        def discovery_device_info(self, deviceid, ha_devicename):
            return {'name': ha_devicename}

    rs485.Pico2CHRS485Driver = Base
    rs485.setup = lambda device, index: {'uuid': device['uuid'], 'index': index, 'ports': {}}
    sys.modules['device_modules.pico_2ch_rs485'] = rs485
    sys.modules['pico_2ch_rs485'] = rs485

    spec = importlib.util.spec_from_file_location('device_modules.whes_test', 'device_modules/whes.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WhesTests(unittest.TestCase):
    def test_payload_calculations_and_rounded_energy(self):
        whes = load_whes_module()
        device = {
            'name': 'WHES',
            'uuid': '0001',
            'type': {'class': 'sensor', 'subclass': 'WHES'},
            'entities': {
                '0': {'class': 'power', 'key': 'PPV1', 'value': 1000},
                '1': {'class': 'power', 'key': 'PPV2', 'value': 500},
                '2': {'class': 'power', 'key': 'BatPower_BMS', 'value': -300},
                '3': {'class': 'power', 'key': 'Power_Meter', 'value': -200},
                '4': {'class': 'battery', 'key': 'BatSOC', 'value': 64}
            }
        }
        driver = whes.WHESDriver(device, {})
        driver._energy_day = driver._current_day()
        driver._energy_ticks = driver._ticks_ms() - 60000

        values = driver._calculated_values()
        driver._update_energy_totals(values)
        driver._add_energy_values(values)
        payload = driver._presentation_payload(values)

        self.assertNotIn('PPV1', payload)
        self.assertNotIn('PPV2', payload)
        self.assertEqual(payload['PV_p'], 1500)
        self.assertEqual(payload['battery_p'], 300)
        self.assertEqual(payload['grid_p'], -200)
        self.assertEqual(payload['home_p'], 1800)
        self.assertEqual(payload['battery_soc'], 64)
        self.assertNotIn('battery_charge_p', payload)
        self.assertNotIn('battery_discharge_p', payload)
        self.assertNotIn('grid_import_p', payload)
        self.assertNotIn('grid_export_p', payload)
        self.assertEqual(payload['battery_discharge_e'], 0.005)
        self.assertEqual(payload['grid_export_e'], 0.0033)

    def test_discovery_uses_presentation_order_indexes(self):
        whes = load_whes_module()
        device = {
            'name': 'WHES',
            'uuid': '0001',
            'type': {'class': 'sensor', 'subclass': 'WHES'},
            'entities': {}
        }
        driver = whes.WHESDriver(device, {})

        discovery, _ = driver.get_discovery_payloads('abc', 'WHES Device')

        self.assertEqual(sorted(discovery.keys()), list(range(len(whes.PRESENTATION_ENTITIES))))
        self.assertEqual(discovery[9]['name'], 'WHES grid_import_e')
        self.assertEqual(discovery[9]['uniq_id'], 'abc0001_9')
        self.assertEqual(discovery[10]['name'], 'WHES grid_export_e')
        self.assertEqual(discovery[10]['uniq_id'], 'abc0001_10')


if __name__ == '__main__':
    unittest.main()
