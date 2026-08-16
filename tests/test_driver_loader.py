import unittest
from unittest.mock import patch

from device_modules import loader


class DriverLoaderTests(unittest.TestCase):
    def tearDown(self):
        loader._MODULES = []
        loader._DEVICE_TYPES = {}

    def test_imports_only_drivers_used_by_configuration(self):
        class FakeWhes:
            DEVICE_TYPE = {'class': 'sensor', 'subclass': {'WHES': {}}}

            @staticmethod
            def supports(device):
                return device.get('type', {}).get('subclass') == 'WHES'

        imported = []

        def import_driver(name):
            imported.append(name)
            return FakeWhes

        devices = [
            {'type': {'class': 'sensor', 'subclass': 'WHES'}},
            {'type': {'class': 'sensor', 'subclass': 'WHES'}},
        ]
        with patch.object(loader, '_import_driver', side_effect=import_driver):
            types = loader.configure_for_devices(devices)

        self.assertEqual(imported, ['whes'])
        self.assertEqual(types, [FakeWhes.DEVICE_TYPE])

    def test_unknown_configured_type_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, 'no packaged driver'):
            loader.configure_for_devices([
                {'type': {'class': 'sensor', 'subclass': 'Unknown'}}
            ])

    def test_validation_import_does_not_replace_active_drivers(self):
        class Driver:
            DEVICE_TYPE = {'class': 'sensor', 'subclass': {'WHES': {}}}

            @staticmethod
            def supports(device):
                return True

        loader._MODULES = ['active']
        loader._DEVICE_TYPES = {'active': {'class': 'sensor'}}
        with patch.object(loader, '_import_driver', return_value=Driver):
            types = loader.device_types_for_devices([
                {'type': {'class': 'sensor', 'subclass': 'WHES'}}
            ])
        self.assertEqual(types, [Driver.DEVICE_TYPE])
        self.assertEqual(loader._MODULES, ['active'])
        self.assertEqual(loader._DEVICE_TYPES, {'active': {'class': 'sensor'}})

    def test_setup_failure_returns_visible_diagnostic_record(self):
        class BrokenDriver:
            __name__ = 'broken_driver'

            @staticmethod
            def setup(device, index):
                raise RuntimeError('ESP_ERR_INVALID_STATE')

        device = {
            'name': 'Greenstar 8000',
            'uuid': '0001',
            'type': {'class': 'sensor', 'subclass': 'EMS-Boiler'},
        }
        with patch.object(loader, '_find_module_for_device', return_value=BrokenDriver):
            with patch.object(loader, 'log_output'):
                result = loader.setup_device(device, 1)

        self.assertEqual(result['uuid'], '0001')
        self.assertEqual(result['index'], 1)
        self.assertEqual(result['setup_error'], 'ESP_ERR_INVALID_STATE')


if __name__ == '__main__':
    unittest.main()
