import unittest

from device_modules.base import ha_config_topic
from device_modules.base import ha_response_topic
from device_modules.base import ha_set_topic
from device_modules.base import ha_state_topic
from device_modules.validation import validate_device_config


DEVICE_TYPES = [
    {
        'class': 'sensor',
        'subclass': {
            'WHES': {
                'entities': {
                    'battery',
                    'memory_value',
                    'power'
                }
            }
        }
    }
]


class HelperTests(unittest.TestCase):
    def test_home_assistant_topics(self):
        self.assertEqual(
            ha_state_topic('sensor', 'abc', '0001'),
            'homeassistant/sensor/abc0001/state'
        )
        self.assertEqual(
            ha_config_topic('sensor', 'abc', '0001', 2),
            'homeassistant/sensor/abc0001_2/config'
        )
        self.assertEqual(
            ha_set_topic('sensor', 'abc', '0001'),
            'homeassistant/sensor/abc0001/set'
        )
        self.assertEqual(
            ha_response_topic('sensor', 'abc', '0001'),
            'homeassistant/sensor/abc0001/response'
        )

    def test_config_validation_accepts_current_shape(self):
        config = {
            'devices': [
                {
                    'name': 'WHES',
                    'uuid': '0001',
                    'type': {'class': 'sensor', 'subclass': 'WHES'},
                    'rs485': {},
                    'entities': {
                        '0': {
                            'class': 'power',
                            'key': 'PPV1',
                            'address': 36112,
                            'count': 1,
                            'data_type': 'uint16'
                        },
                        '1': {
                            'class': 'memory_value',
                            'key': 'SerialNumber',
                            'address': 36010,
                            'count': 10,
                            'data_type': 'ascii'
                        },
                        '2': {
                            'class': 'battery',
                            'key': 'BatSOC',
                            'address': 36155,
                            'count': 1,
                            'data_type': 'uint16'
                        }
                    }
                }
            ]
        }
        self.assertEqual(validate_device_config(config, DEVICE_TYPES), [])

    def test_config_validation_rejects_duplicate_keys(self):
        config = {
            'devices': [
                {
                    'name': 'WHES',
                    'uuid': '0001',
                    'type': {'class': 'sensor', 'subclass': 'WHES'},
                    'entities': {
                        '0': {'class': 'power', 'key': 'x', 'address': 1},
                        '1': {'class': 'power', 'key': 'x', 'address': 2}
                    }
                }
            ]
        }
        errors = validate_device_config(config, DEVICE_TYPES)
        self.assertTrue(any('duplicate key x' in error for error in errors))


if __name__ == '__main__':
    unittest.main()
