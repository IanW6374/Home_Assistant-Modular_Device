import json
import unittest

import settings_loader


class SettingsLoaderTests(unittest.TestCase):
    def test_current_device_settings_load(self):
        with open('device_settings.json', 'r') as fh:
            config = json.load(fh)

        self.assertEqual(settings_loader.module_settings_file, config['device']['module_settings_file'])
        self.assertEqual(settings_loader.ha_device_name, config['device']['name'])
        self.assertEqual(settings_loader.ha_discovery, config['ha']['discovery'])
        self.assertEqual(
            settings_loader.ha_discovery_cleanup_legacy_identity,
            config['ha']['discovery_cleanup_legacy_identity']
        )
        self.assertEqual(settings_loader.ha_device_info.get('mdl'), config['ha']['device_info'].get('mdl'))
        self.assertEqual(settings_loader.web_portal_enabled, config['web_portal']['enabled'])
        self.assertEqual(settings_loader.web_portal_log_refresh_s, config['web_portal']['log_refresh_s'])
        self.assertEqual(settings_loader.web_portal_value_refresh_s, config['web_portal']['value_refresh_s'])
        self.assertEqual(settings_loader.web_log_buffer_lines, config['web_portal']['log_buffer_lines'])
        self.assertEqual(settings_loader.web_log_line_max_chars, config['web_portal']['log_line_max_chars'])
        self.assertEqual(settings_loader.web_portal_updates_enabled, config['web_portal']['updates_enabled'])
        self.assertEqual(settings_loader.web_portal_update_max_bytes, config['web_portal']['update_max_bytes'])
        self.assertEqual(
            settings_loader.web_portal_allow_protected_updates,
            config['web_portal']['allow_protected_updates']
        )
        self.assertEqual(
            settings_loader.web_portal_firmware_updates_enabled,
            config['web_portal']['firmware_updates_enabled']
        )
        self.assertEqual(
            settings_loader.web_portal_firmware_update_max_bytes,
            config['web_portal']['firmware_update_max_bytes']
        )
        self.assertEqual(settings_loader.status_led_pin, config['device']['status_led_pin'])
        self.assertEqual(settings_loader.status_led_type, config['device']['status_led_type'])
        self.assertEqual(settings_loader.local_display.get('enabled'), config['local_display']['enabled'])
        self.assertIn(settings_loader.loglevel, ('ERROR', 'INFO', 'DEBUG'))

    def test_required_json_rejects_missing_file(self):
        with self.assertRaisesRegex(RuntimeError, 'Required JSON settings file not found'):
            settings_loader.load_required_json('missing-device-settings-test.json')

    def test_ntp_servers_validated_as_non_empty_list(self):
        with self.assertRaisesRegex(RuntimeError, 'ntp_servers must be a non-empty list'):
            settings_loader._validate_ntp_servers([])

    def test_loglevel_validated(self):
        with self.assertRaisesRegex(RuntimeError, 'device.loglevel must be ERROR, INFO, or DEBUG'):
            settings_loader._validate_loglevel('TRACE')

    def test_optional_sections_default_disabled(self):
        self.assertEqual(settings_loader._section({}, 'ha'), {})
        self.assertEqual(settings_loader._section({}, 'web_portal'), {})
        self.assertEqual(settings_loader._section({}, 'local_display'), {})

    def test_required_device_section_is_enforced(self):
        with self.assertRaisesRegex(RuntimeError, 'missing device'):
            settings_loader._section({}, 'device', True)

    def test_unknown_keys_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'unknown device.old_name'):
            settings_loader._reject_unknown({'old_name': 'Controller'}, ('name',), 'device')


if __name__ == '__main__':
    unittest.main()
