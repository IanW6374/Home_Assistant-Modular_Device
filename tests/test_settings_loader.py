import json
import tempfile
import unittest
from pathlib import Path

import device_config
import settings_loader


class SettingsLoaderTests(unittest.TestCase):
    def test_signed_application_settings_load(self):
        with open('app_settings.json', 'r') as settings_file:
            config = json.load(settings_file)

        self.assertEqual(
            settings_loader.ha_system_diagnostics,
            config['ha']['system_diagnostics']
        )
        self.assertEqual(
            settings_loader.web_portal_enabled,
            config['web_portal']['enabled']
        )
        self.assertEqual(
            settings_loader.web_portal_log_refresh_s,
            config['web_portal']['log_refresh_s']
        )
        self.assertEqual(
            settings_loader.web_portal_value_refresh_s,
            config['web_portal']['value_refresh_s']
        )
        self.assertEqual(
            settings_loader.release_manifest_url,
            config['web_portal']['release_manifest_url']
        )
        self.assertEqual(
            settings_loader.local_display,
            config['local_display']
        )

    def test_immutable_device_policy_comes_from_frozen_module(self):
        self.assertEqual(
            settings_loader.module_settings_file,
            device_config.MODULE_SETTINGS_FILE
        )
        self.assertEqual(
            settings_loader.watchdog_timeout_ms,
            device_config.WATCHDOG_TIMEOUT_MS
        )
        self.assertEqual(
            settings_loader.status_led_pin,
            device_config.STATUS_LED_PIN
        )
        self.assertEqual(
            settings_loader.web_portal_cert_path,
            device_config.WEB_PORTAL_CERT_PATH
        )
        self.assertEqual(
            settings_loader.api_server_cert_path,
            device_config.API_SERVER_CERT_PATH
        )
        self.assertNotEqual(
            settings_loader.api_server_cert_path,
            settings_loader.web_portal_cert_path
        )
        self.assertEqual(
            settings_loader.web_portal_update_max_bytes,
            device_config.WEB_PORTAL_UPDATE_MAX_BYTES
        )
        self.assertEqual(
            settings_loader.ha_device_info['mdl'],
            device_config.DEVICE_INFO['mdl']
        )
        self.assertEqual(settings_loader.ha_device_info['mf'], 'IoT-MD')
        self.assertEqual(
            settings_loader.ha_device_info['mdl'],
            'IoT Modular Device'
        )
        self.assertEqual(
            settings_loader.ha_device_info['hw'],
            'ESP32-S3-DevKitC-1-N8R8'
        )

    def test_user_preferences_have_safe_unprovisioned_defaults(self):
        self.assertEqual(settings_loader.loglevel, 'INFO')
        self.assertTrue(settings_loader.ha_discovery)
        self.assertEqual(settings_loader.ha_discovery_prefix, 'homeassistant')
        self.assertEqual(settings_loader.mqtt_base_topic, 'iotmd')
        self.assertEqual(
            settings_loader.mqtt_state_topic,
            '{base}/{device_id}/{module_id}/state'
        )
        self.assertFalse(settings_loader.release_auto_download)
        self.assertFalse(settings_loader.release_auto_activate)
        self.assertEqual(settings_loader.release_check_schedule, 'disabled')
        self.assertEqual(settings_loader.release_check_time, '03:00')
        self.assertEqual(settings_loader.release_check_weekday, 0)
        self.assertTrue(settings_loader.ntp_servers)

    def test_tls_services_have_independent_paths_with_legacy_fallback(self):
        self.assertEqual(
            settings_loader.service_ca_path('mqtt', exists=lambda _path: False),
            device_config.TRUST_CA_PATH
        )
        self.assertEqual(
            settings_loader.service_ca_path('release', exists=lambda _path: False),
            device_config.TRUST_CA_PATH
        )
        self.assertEqual(
            settings_loader.service_ca_path('mqtt', exists=lambda _path: True),
            device_config.MQTT_CA_PATH
        )
        self.assertEqual(
            settings_loader.service_ca_path('release', exists=lambda _path: True),
            device_config.RELEASE_CA_PATH
        )
        self.assertEqual(
            settings_loader.service_ca_path('api_client', exists=lambda _path: False),
            device_config.API_CLIENT_CA_PATH
        )
        with self.assertRaisesRegex(ValueError, 'unknown TLS service'):
            settings_loader.service_ca_path('other')

    def test_missing_optional_ca_does_not_prevent_portal_startup(self):
        original = device_config.TRUST_CA_PATH
        with tempfile.TemporaryDirectory() as directory:
            device_config.TRUST_CA_PATH = str(Path(directory) / 'missing.der')
            try:
                self.assertEqual(
                    settings_loader.service_ca_bytes('mqtt', required=False), b''
                )
                with self.assertRaisesRegex(RuntimeError, 'trusted CA is unavailable'):
                    settings_loader.service_ca_bytes('mqtt', required=True)
            finally:
                device_config.TRUST_CA_PATH = original

    def test_required_json_rejects_missing_file(self):
        with self.assertRaisesRegex(
            RuntimeError, 'Required JSON settings file not found'
        ):
            settings_loader.load_required_json('missing-app-settings-test.json')

    def test_optional_sections_default_to_empty_objects(self):
        self.assertEqual(settings_loader._section({}, 'ha'), {})
        self.assertEqual(settings_loader._section({}, 'web_portal'), {})
        self.assertEqual(settings_loader._section({}, 'local_display'), {})

    def test_section_type_and_unknown_keys_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'ha must be an object'):
            settings_loader._section({'ha': []}, 'ha')
        with self.assertRaisesRegex(RuntimeError, 'unknown ha.old_name'):
            settings_loader._reject_unknown(
                {'old_name': 'Controller'}, ('system_diagnostics',), 'ha'
            )


if __name__ == '__main__':
    unittest.main()
