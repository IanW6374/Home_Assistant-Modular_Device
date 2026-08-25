import unittest
from unittest.mock import patch

import device_modules.base as base
from device_modules.base import ha_config_topic
from device_modules.base import mqtt_availability_topic
from device_modules.base import mqtt_response_topic
from device_modules.base import ha_safe_id
from device_modules.base import mqtt_command_topic
from device_modules.base import mqtt_state_topic
from device_modules.base import ha_unique_id
from device_modules.base import sensor_discovery_payload
from device_modules.base import DeviceDriver
from device_modules.base import homeassistant_device_info
from device_modules.base import module_diagnostics_need_attention
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


class TestDriver(DeviceDriver):
    def get_discovery_payloads(self, deviceid, ha_devicename):
        return {}, {}

    def get_state_payload(self):
        return {'temperature': 21}


class ModuleDiagnosticsTests(unittest.TestCase):
    def test_failed_status_needs_attention_without_error_text(self):
        self.assertTrue(module_diagnostics_need_attention({'last_ok': False}))

    def test_prefixed_transport_status_and_errors_need_attention(self):
        self.assertTrue(module_diagnostics_need_attention({
            'module_rs485_last_ok': False,
            'module_rs485_last_error': '',
        }))
        self.assertTrue(module_diagnostics_need_attention({
            'ems_last_ok': True,
            'ems_last_error': 'crc mismatch',
        }))

    def test_healthy_or_uninitialised_diagnostics_do_not_need_attention(self):
        self.assertFalse(module_diagnostics_need_attention({'last_ok': True}))
        self.assertFalse(module_diagnostics_need_attention({'last_ok': None}))
        self.assertFalse(module_diagnostics_need_attention({}))


class HelperTests(unittest.TestCase):
    def test_mqtt_topics_are_platform_neutral(self):
        self.assertEqual(
            mqtt_state_topic('sensor', 'abc', '0001'),
            'iotmd/abc/0001/state'
        )
        self.assertEqual(
            ha_config_topic('sensor', 'abc', '0001', 2),
            'homeassistant/sensor/abc0001_2/config'
        )
        self.assertEqual(
            mqtt_command_topic('sensor', 'abc', '0001'),
            'iotmd/abc/0001/set'
        )
        self.assertEqual(
            mqtt_response_topic('sensor', 'abc', '0001'),
            'iotmd/abc/0001/response'
        )
        self.assertEqual(
            mqtt_availability_topic('abc'),
            'iotmd/abc/availability'
        )

    def test_mqtt_topic_templates_are_configurable(self):
        with (
            patch.object(base.device_settings, 'mqtt_base_topic', 'plant'),
            patch.object(
                base.device_settings, 'mqtt_state_topic',
                '{base}/{component}/{device_id}/{module_id}/value'
            ),
            patch.object(
                base.device_settings, 'mqtt_command_topic',
                '{base}/{device_id}/commands/{module_id}'
            ),
        ):
            self.assertEqual(
                mqtt_state_topic('sensor', 'boiler', 'flow'),
                'plant/sensor/boiler/flow/value'
            )
            self.assertEqual(
                mqtt_command_topic('sensor', 'boiler', 'flow'),
                'plant/boiler/commands/flow'
            )

    def test_home_assistant_safe_ids(self):
        self.assertEqual(ha_safe_id('PowerLimitByBMSDisChg'), 'powerlimitbybmsdischg')
        self.assertEqual(ha_safe_id('grid import e'), 'grid_import_e')
        self.assertEqual(ha_safe_id('AC Present?'), 'ac_present')
        self.assertEqual(ha_unique_id('abc', '0001', 'grid_import_e'), 'abc0001_grid_import_e')

    def test_home_assistant_device_info_uses_configured_name_and_serial(self):
        info = homeassistant_device_info(
            'abc123_configured_device', 'Configured Device'
        )

        self.assertEqual(info['name'], 'Configured Device')
        self.assertEqual(info['ids'], ['abc123_configured_device'])
        self.assertEqual(info['sn'], 'abc123')
        self.assertEqual(info['mf'], 'IoTMD')
        self.assertEqual(info['mdl'], 'IoT Modular Device')
        self.assertEqual(info['hw'], 'ESP32-S3-DevKitC-1-N8R8')

    def test_sensor_discovery_includes_availability_and_origin(self):
        payload = sensor_discovery_payload(
            {
                'name': 'Probe',
                'uuid': '0001',
                'type': {'class': 'sensor'},
                '_portal_url': 'http://192.168.1.50:8080/'
            },
            {'class': 'temperature', 'key': 'temperature'},
            'temperature',
            '0',
            'abc',
            'Device'
        )

        self.assertEqual(payload['availability_topic'], 'iotmd/abc/availability')
        self.assertEqual(payload['payload_available'], 'online')
        self.assertEqual(payload['payload_not_available'], 'offline')
        self.assertEqual(payload['dev']['cu'], 'http://192.168.1.50:8080/')
        self.assertIn('o', payload)

    def test_sensor_discovery_disables_diagnostics_by_default(self):
        payload = sensor_discovery_payload(
            {'name': 'Probe', 'uuid': '0001', 'type': {'class': 'sensor'}},
            {'class': 'memory_value', 'entity_category': 'diagnostic'},
            'module_last_error',
            '0',
            'abc',
            'Device'
        )

        self.assertEqual(payload['entity_category'], 'diagnostic')
        self.assertFalse(payload['en'])
        self.assertNotIn('enabled_by_default', payload)
        self.assertNotIn('entity_registry_enabled_default', payload)

    def test_sensor_discovery_keeps_measurements_enabled_by_default(self):
        payload = sensor_discovery_payload(
            {'name': 'Probe', 'uuid': '0001', 'type': {'class': 'sensor'}},
            {'class': 'temperature', 'key': 'temperature'},
            'temperature',
            '0',
            'abc',
            'Device'
        )

        self.assertNotIn('en', payload)
        self.assertNotIn('enabled_by_default', payload)
        self.assertNotIn('entity_registry_enabled_default', payload)

    def test_publish_state_includes_health_after_mark_publish(self):
        driver = TestDriver(
            {'name': 'Probe', 'uuid': '0001', 'type': {'class': 'sensor'}},
            {}
        )
        published = []

        driver.mark_read_ok(12)
        driver.publish_state(lambda data, qos, log_only, retain: published.append(data), 'abc')

        payload = published[0]['payload']
        self.assertEqual(payload['temperature'], 21)
        self.assertTrue(payload['module_last_ok'])
        self.assertEqual(payload['module_last_error'], '')
        self.assertEqual(payload['module_last_read_ms'], 12)
        self.assertIsInstance(payload['module_last_publish_age_s'], int)

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
