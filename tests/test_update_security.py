import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import recovery_boot
import update_security
import update_support
import release_update
import wifi_recovery
from tools.build_update import build_bundle


class UpdateSecurityTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)

    def tearDown(self):
        update_support.release_update_lock()
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def test_signed_manifest_is_required_after_key_provisioning(self):
        key = bytes(range(32))
        Path(update_security.SIGNING_KEY_PATH).write_bytes(key)
        source = Path('source.py')
        source.write_text('VALUE = 1')
        build_bundle(Path('signed.hamd'), '2.0', [('HA-Device.py', source)], signing_key=key)

        with Path('signed.hamd').open('rb') as stream:
            import app_update
            manifest = app_update.read_manifest(stream)
        self.assertEqual(manifest['format_version'], 2)
        self.assertEqual(manifest['signature_scheme'], 'hmac-sha256')

        build_bundle(Path('unsigned.hamd'), '2.0', [('HA-Device.py', source)])
        with Path('unsigned.hamd').open('rb') as stream:
            with self.assertRaisesRegex(ValueError, 'signed updates are required'):
                app_update.read_manifest(stream)

    def test_wrong_signature_is_rejected(self):
        Path(update_security.SIGNING_KEY_PATH).write_bytes(bytes(range(32)))
        manifest = {
            'format_version': 2,
            'target_board': 'esp32-s3',
            'min_recovery_api': 2,
            'max_recovery_api': 2,
            'version': '1',
            'files': [],
            'signature_scheme': 'hmac-sha256',
            'signature': '0' * 64,
        }
        with self.assertRaisesRegex(ValueError, 'signature verification failed'):
            update_security.validate_manifest('hamd', manifest)

    def test_recovery_api_incompatibility_is_rejected(self):
        manifest = {
            'format_version': 2,
            'target_board': 'esp32-s3',
            'min_recovery_api': 3,
            'max_recovery_api': 4,
            'version': 'future',
            'files': [],
        }
        with self.assertRaisesRegex(ValueError, 'installed API is 2'):
            update_security.validate_manifest('hamd', manifest)

    def test_application_checks_api_exposed_by_frozen_recovery(self):
        manifest = {
            'format_version': 2,
            'target_board': 'esp32-s3',
            'min_recovery_api': 2,
            'max_recovery_api': 2,
            'version': 'api-2-app',
            'files': [],
        }
        with patch.object(recovery_boot, 'RECOVERY_API_VERSION', 1):
            with self.assertRaisesRegex(ValueError, 'installed API is 1'):
                update_security.validate_manifest('hamd', manifest)

    def test_base_firmware_can_upgrade_an_older_recovery_api(self):
        manifest = {
            'format_version': 2,
            'target_board': 'esp32-s3',
            'min_recovery_api': 2,
            'max_recovery_api': 2,
            'version': 'api-2-firmware',
            'size': 1,
            'sha256': '0' * 64,
        }
        with patch.object(recovery_boot, 'RECOVERY_API_VERSION', 1):
            result = update_security.validate_manifest('hamf', manifest)
        self.assertFalse(result['signed'])

    def test_lock_and_bounded_history(self):
        update_support.acquire_update_lock()
        with self.assertRaisesRegex(RuntimeError, 'already in progress'):
            update_support.acquire_update_lock()
        update_support.release_update_lock()
        for index in range(25):
            update_support.record_update_event('application', 'event', str(index))
        history = update_support.update_history()
        self.assertEqual(len(history), update_support.MAX_HISTORY)
        self.assertEqual(history[-1]['version'], '24')

    def test_wifi_recovery_replaces_only_wifi_assignments(self):
        Path('secrets.py').write_text(
            "wifi_ssid = 'old'\n"
            "wifi_password = 'old-password'\n"
            "mqtt_password = 'preserved'\n"
        )
        wifi_recovery._replace_secret_assignments(
            'secrets.py', "new-network", "new-password"
        )
        content = Path('secrets.py').read_text()
        self.assertIn("wifi_ssid = 'new-network'", content)
        self.assertIn("wifi_password = 'new-password'", content)
        self.assertIn("mqtt_password = 'preserved'", content)

    def test_release_client_requires_https(self):
        self.assertEqual(
            release_update._parse_https_url('https://updates.example:8443/latest.json'),
            ('updates.example', 8443, '/latest.json')
        )
        with self.assertRaisesRegex(ValueError, 'must use HTTPS'):
            release_update._parse_https_url('http://updates.example/latest.json')


if __name__ == '__main__':
    unittest.main()
