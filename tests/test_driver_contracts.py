import unittest
from unittest.mock import patch

from device_modules import contracts, loader


class FakeDriver:
    def set(self, payload):
        return payload

    def set_calibration(self, payload):
        return payload


class FakeModule:
    MODULE_VERSION = 3
    DEVICE_TYPE = {'class': 'sensor', 'subclass': {'Example': {}}}
    Driver = FakeDriver

    @staticmethod
    def supports(_device):
        return True


class DriverContractTests(unittest.TestCase):
    def tearDown(self):
        loader._MODULES = []
        loader._DEVICE_TYPES = {}
        loader._DRIVER_METADATA = {}

    def test_synthesises_v2_metadata_for_existing_driver(self):
        metadata = contracts.metadata_for('example', FakeModule)
        self.assertEqual(metadata['api_version'], 2)
        self.assertEqual(metadata['version'], 3)
        self.assertEqual(metadata['types'], ['sensor:Example'])
        self.assertIn('commands', metadata['capabilities'])
        self.assertIn('calibration', metadata['capabilities'])

    def test_loader_exposes_only_configured_driver_metadata(self):
        devices = [{'type': {'class': 'sensor', 'subclass': 'WHES'}}]
        with patch.object(loader, '_import_driver', return_value=FakeModule):
            loader.configure_for_devices(devices)

        catalog = loader.driver_catalog()
        self.assertEqual(catalog[0]['name'], 'whes')
        self.assertEqual(catalog[0]['api_version'], 2)

    def test_contract_rejects_unknown_capability(self):
        with self.assertRaisesRegex(ValueError, 'capabilities'):
            contracts.validate_metadata({
                'name': 'bad', 'api_version': 2, 'version': 1,
                'types': ['sensor:Bad'], 'capabilities': ['shell'],
                'configuration_schema': {},
            })


if __name__ == '__main__':
    unittest.main()
