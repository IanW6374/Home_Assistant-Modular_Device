import json
import unittest

import configuration_manager


class ConfigurationManagerTests(unittest.TestCase):
    def test_export_is_versioned_and_excludes_secret_markers(self):
        backup = configuration_manager.export_configuration({
            'device_name': 'Controller',
            'wifi_ssid': 'network',
            'wifi_password_set': True,
            'mqtt_password_set': True,
            'api_enabled': True,
            'api_port': 8444,
            'timezone_name': 'Europe/London',
            'certificate_mode': 'acme',
            'acme_directory_url': 'https://acme.example/directory',
            'certificate_hostname': 'controller.local',
        }, {'devices': []})

        self.assertEqual(backup['format_version'], 4)
        self.assertFalse(backup['secrets_included'])
        self.assertNotIn('wifi_password_set', backup['settings'])
        self.assertNotIn('mqtt_password_set', backup['settings'])
        self.assertEqual(backup['settings']['timezone_name'], 'Europe/London')
        self.assertEqual(backup['settings']['certificate_mode'], 'acme')
        self.assertEqual(
            backup['settings']['acme_directory_url'],
            'https://acme.example/directory'
        )
        self.assertEqual(
            backup['settings']['certificate_hostname'], 'controller.local'
        )

    def test_prepare_validates_and_returns_field_diff(self):
        payload = configuration_manager.export_configuration(
            {'device_name': 'New', 'wifi_ssid': 'network'},
            {'devices': [{'uuid': '0001'}]}
        )
        validated = []
        plan = configuration_manager.prepare_import(
            json.dumps(payload),
            {'device_name': 'Old', 'wifi_ssid': 'network'},
            {'devices': []},
            lambda values: validated.append(values),
            lambda modules: []
        )

        self.assertEqual(validated[0]['device_name'], 'New')
        self.assertEqual(plan['change_count'], 2)
        self.assertIn('settings.device_name', [item['path'] for item in plan['changes']])

    def test_rejects_secret_or_unknown_settings(self):
        payload = {
            'format_version': 4,
            'secrets_included': False,
            'settings': {'wifi_password': 'secret'},
        }
        with self.assertRaisesRegex(ValueError, 'not importable'):
            configuration_manager.parse_import(payload)

    def test_rejects_invalid_modules_before_apply(self):
        payload = configuration_manager.export_configuration(
            {}, {'devices': [{'uuid': 'bad'}]}
        )
        with self.assertRaisesRegex(ValueError, 'module configuration rejected'):
            configuration_manager.prepare_import(
                payload, {}, {}, lambda _values: True,
                lambda _modules: ['invalid UUID']
            )

    def test_complete_backup_encrypts_secrets_and_authenticates_password(self):
        backup = configuration_manager.export_secure_configuration(
            {'schema': 5, 'wifi': {'password': 'very-secret'}},
            {'devices': []}, {'portal_private_key': b'private-key'},
            'Backup-Cedar-47!River', random_bytes=lambda count: bytes(range(count))
        )

        encoded = json.dumps(backup)
        self.assertNotIn('very-secret', encoded)
        self.assertNotIn('private-key', encoded)
        restored = configuration_manager.parse_secure_import(
            backup, 'Backup-Cedar-47!River'
        )
        self.assertEqual(restored['credentials']['wifi']['password'], 'very-secret')
        self.assertEqual(restored['files']['portal_private_key'], b'private-key')
        with self.assertRaisesRegex(ValueError, 'authentication failed'):
            configuration_manager.parse_secure_import(
                backup, 'Wrong-Backup-47!River'
            )

    def test_null_format_version_has_a_clear_validation_error(self):
        with self.assertRaisesRegex(ValueError, 'unsupported configuration backup format'):
            configuration_manager.parse_import({
                'format_version': None,
                'secrets_included': False,
                'settings': {},
            })

    def test_secure_restore_preview_is_structured_and_never_exposes_secrets(self):
        preview = configuration_manager.secure_restore_preview(
            {
                'device_name': 'Current controller',
                'wifi': {'ssid': 'old-network', 'password': 'current-secret'},
                'mqtt': {'server': 'old-broker', 'password': 'current-mqtt-secret'},
                'portal': {'username': 'admin', 'password': 'current-portal-secret'},
            },
            {'devices': [{'uuid': '0001', 'name': 'Current module'}]},
            {'portal_private_key': b'current-private-key'},
            {
                'credentials': {
                    'device_name': 'Restored controller',
                    'wifi': {'ssid': 'new-network', 'password': 'backup-secret'},
                    'mqtt': {'server': 'new-broker', 'password': 'backup-mqtt-secret'},
                    'portal': {'username': 'operator', 'password': 'backup-portal-secret'},
                },
                'module_settings': {
                    'devices': [{'uuid': '0002', 'name': 'Restored module'}]
                },
                'files': {'mqtt_ca': b'backup-ca', 'api_client_ca_1': b'backup-client-ca'},
                'metadata': {'device_id': 'restored-device'},
            },
            'current-device'
        )

        paths = [row['path'] for row in preview['changes']]
        encoded = json.dumps(preview)
        self.assertEqual(preview['change_count'], len(preview['changes']))
        self.assertIn('Wi-Fi network', paths)
        self.assertIn('Module configuration', paths)
        self.assertIn('Certificates, keys and trust', paths)
        states = {row['path']: row['state'] for row in preview['changes']}
        self.assertEqual(states['Device name'], 'changed')
        self.assertEqual(states['Wi-Fi network'], 'changed')
        self.assertEqual(states['Backup source device'], 'changed')
        self.assertIn(states['Secret credentials'], ('same', 'missing'))
        self.assertNotIn('current-secret', encoded)
        self.assertNotIn('backup-secret', encoded)
        self.assertNotIn('current-private-key', encoded)
        self.assertNotIn('backup-ca', encoded)

    def test_secure_restore_preview_can_select_sections(self):
        preview = configuration_manager.secure_restore_preview(
            {}, {'devices': []}, {}, {
                'metadata': {}, 'credentials': {},
                'module_settings': {'devices': [{'name': 'Only module'}]},
                'files': {},
            }, sections=['module_settings']
        )

        self.assertEqual(preview['sections'], ['module_settings'])
        self.assertEqual(
            [row['path'] for row in preview['changes']],
            ['Module configuration']
        )

    def test_restore_sections_reject_empty_and_unknown_values(self):
        with self.assertRaisesRegex(ValueError, 'at least one'):
            configuration_manager.validate_restore_sections([])
        with self.assertRaisesRegex(ValueError, 'not supported'):
            configuration_manager.validate_restore_sections(['shell'])


if __name__ == '__main__':
    unittest.main()
