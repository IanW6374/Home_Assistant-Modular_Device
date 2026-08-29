import json
import hashlib
import os
import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch

import recovery_boot
import update_security
import update_support
import release_update
import wifi_recovery
import credential_security
import credential_store
from tools.build_update import build_bundle
from tools.build_firmware_update import build_firmware_bundle
from tools.publish_release import notes_with_source, publish_release


class UpdateSecurityTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)
        self.private_key = bytes(range(1, 33))
        self.public_key = update_security.public_key_bytes(self.private_key)
        Path(update_security.VERIFICATION_KEY_PATH).write_bytes(self.public_key)
        credential_store._reset_memory_backend()

    def tearDown(self):
        update_support.release_update_lock()
        credential_store._reset_memory_backend()
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def test_highest_bit_does_not_require_int_bit_length(self):
        self.assertEqual(update_security._highest_bit(0), 0)
        self.assertEqual(update_security._highest_bit(1), 1)
        self.assertEqual(update_security._highest_bit(255), 128)
        self.assertEqual(update_security._highest_bit(256), 256)

    def test_automatic_release_check_schedule_uses_local_time(self):
        monday_at_three = (2026, 8, 24, 3, 0, 0, 0, 236)
        self.assertEqual(
            release_update.automatic_check_slot(
                'daily', '03:00', 6, monday_at_three
            ),
            '20260824'
        )
        self.assertEqual(
            release_update.automatic_check_slot(
                'weekly', '03:00', 0, monday_at_three
            ),
            '20260824'
        )
        self.assertEqual(
            release_update.automatic_check_slot(
                'weekly', '03:00', 6, monday_at_three
            ),
            ''
        )
        self.assertEqual(
            release_update.automatic_check_slot(
                'disabled', '03:00', 0, monday_at_three
            ),
            ''
        )
        self.assertEqual(
            release_update.automatic_check_slot(
                'daily', '03:01', 0, monday_at_three
            ),
            ''
        )

    def test_shared_json_recovers_previous_generation_after_interruption(self):
        Path('module_settings.json').write_text('{"devices":[{"name":"old"}]}')
        Path('module_settings.json.tmp').write_text('{"devices":[{"name":"new"}]}')
        update_support.commit_file_with_backup(
            'module_settings.json.tmp', 'module_settings.json'
        )
        Path('module_settings.json').write_text('{broken')

        recovered = update_support.load_json_with_backup('module_settings.json')
        self.assertEqual(recovered['devices'][0]['name'], 'old')
        self.assertEqual(
            json.loads(Path('module_settings.json').read_text()), recovered
        )

    def test_signed_manifest_is_required_after_key_provisioning(self):
        source = Path('source.py')
        source.write_text('VALUE = 1')
        build_bundle(
            Path('signed.iotapp'), '3.0', [('iotmd.py', source)],
            signing_key=self.private_key
        )

        with Path('signed.iotapp').open('rb') as stream:
            import app_update
            manifest = app_update.read_manifest(stream)
        self.assertEqual(manifest['format_version'], 6)
        self.assertEqual(manifest['release_sequence'], 1)
        self.assertEqual(manifest['signature_scheme'], 'ecdsa-p256-sha256')

        build_bundle(Path('unsigned.iotapp'), '2.0', [('iotmd.py', source)])
        with Path('unsigned.iotapp').open('rb') as stream:
            with self.assertRaisesRegex(ValueError, 'ECDSA-signed updates are required'):
                app_update.read_manifest(stream)

    def test_public_update_key_can_come_from_factory_nvs(self):
        Path(update_security.VERIFICATION_KEY_PATH).unlink()
        store = credential_store._nvs()
        store.set_blob('verifykey', self.public_key)
        store.commit()

        self.assertTrue(update_security.signing_enabled())

    def test_wrong_signature_is_rejected(self):
        manifest = {
            'format_version': 6,
            'target_board': 'esp32-s3',
            'min_recovery_api': 6,
            'max_recovery_api': 6,
            'version': '1',
            'release_sequence': 1,
            'minimum_core_api': 6,
            'minimum_config_api': 3,
            'maximum_config_api': 3,
            'components': {'runtime': 1, 'modules': {}},
            'files': [],
            'signature_scheme': 'ecdsa-p256-sha256',
            'signature': '0' * 128,
        }
        with self.assertRaisesRegex(ValueError, 'signature verification failed'):
            update_security.validate_manifest('iotapp', manifest)

    def test_recovery_api_incompatibility_is_rejected(self):
        manifest = {
            'format_version': 6,
            'target_board': 'esp32-s3',
            'min_recovery_api': 7,
            'max_recovery_api': 7,
            'version': 'future',
            'release_sequence': 1,
            'minimum_core_api': 6,
            'minimum_config_api': 3,
            'maximum_config_api': 3,
            'components': {'runtime': 1, 'modules': {}},
            'files': [],
        }
        with self.assertRaisesRegex(ValueError, 'installed API is 6'):
            update_security.validate_manifest('iotapp', manifest)

    def test_application_checks_api_exposed_by_frozen_recovery(self):
        manifest = {
            'format_version': 6,
            'target_board': 'esp32-s3',
            'min_recovery_api': 6,
            'max_recovery_api': 6,
            'version': 'api-6-app',
            'release_sequence': 1,
            'minimum_core_api': 6,
            'minimum_config_api': 3,
            'maximum_config_api': 3,
            'components': {'runtime': 1, 'modules': {}},
            'files': [],
        }
        with patch.object(update_security, 'RECOVERY_API_VERSION', 1):
            with self.assertRaisesRegex(ValueError, 'installed API is 1'):
                update_security.validate_manifest('iotapp', manifest)

    def test_legacy_bundle_format_is_rejected(self):
        manifest = {
            'format_version': 4,
            'target_board': 'esp32-s3',
            'version': 'api-4-firmware',
            'size': 1,
            'sha256': '0' * 64,
        }
        with self.assertRaisesRegex(ValueError, 'unsupported update format'):
            update_security.validate_manifest('iotcore', manifest)

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

    def test_credentials_use_power_safe_encrypted_nvs_slots(self):
        config = credential_store.build_configuration({
            'device_name': 'Controller', 'wifi_ssid': 'old',
            'wifi_password': 'old-password', 'mqtt_server': 'mqtt.local',
            'mqtt_port': '8883', 'mqtt_username': 'user',
            'mqtt_password': 'preserved', 'mqtt_ssl': True,
            'portal_username': 'admin',
            'recovery_ap_password': 'Access-Point-Cedar-47!',
            'profile': 'whes', 'channel': 'stable',
        }, 'Portal-Cedar-47!River', 'Console-Ash-82!Stone')
        credential_store.save(config)
        loaded = credential_store.load()
        loaded['wifi'] = {'ssid': 'new-network', 'password': 'new-password'}
        credential_store.save(loaded)

        self.assertEqual(credential_store.load()['wifi']['ssid'], 'new-network')
        self.assertEqual(credential_store.load()['mqtt']['password'], 'preserved')
        self.assertIn('cfg0', credential_store._memory_values)
        self.assertIn('cfg1', credential_store._memory_values)

    def test_recovery_credentials_are_independently_provisioned(self):
        verifier = credential_security.password_verifier(
            'Console-Ash-82!Stone', bytes(range(16))
        )
        config = {
            'schema': credential_store.SCHEMA_VERSION,
            'provisioned': True, 'device_name': 'Controller',
            'wifi': {'ssid': 'network', 'password': 'wifi-password'},
            'mqtt': {'server': 'mqtt.local', 'port': 8883, 'username': '', 'password': '', 'ssl': True, 'configured': True},
            'portal': {
                'username': 'admin', 'password_verifier': verifier,
                'users': [{
                    'username': 'admin', 'password_verifier': verifier,
                    'role': 'administrator', 'enabled': True,
                }],
            },
            'recovery': {'ap_password': 'Access-Point-Cedar-47!', 'password_verifier': verifier},
            'release': {'channel': 'stable', 'install_mode': 'upload'},
            'certificate': {'mode': 'manual', 'directory_url': '', 'hostname': ''},
            'preferences': {
                'loglevel': 'INFO',
                'ntp_servers': ['pool.ntp.org'],
                'ha_discovery': True,
                'release_auto_download': False,
                'release_auto_activate': False,
            },
        }
        credential_store.save(config)

        self.assertEqual(wifi_recovery.recovery_key(), 'Access-Point-Cedar-47!')
        self.assertEqual(wifi_recovery.recovery_password_verifier(), verifier)

    def test_recovery_key_is_unavailable_before_setup(self):
        self.assertEqual(wifi_recovery.recovery_key(), '')

    def test_recovery_page_only_enables_signed_bundle_uploads(self):
        html = wifi_recovery._recovery_page(
            'application failed', 'csrf-value'
        )

        self.assertIn('IoT-MD core recovery', html)
        self.assertIn('Wi-Fi credentials', html)
        self.assertIn(
            'accept=".iotapp,.iotcore,.iotuni"', html
        )
        self.assertIn('X-CSRF-Token', html)
        self.assertIn('application failed', html)

    def test_core_recovery_console_requires_login_and_csrf(self):
        class AccessPoint:
            def active(self, value):
                self.enabled = value

            def config(self, **kwargs):
                self.settings = kwargs

            def ifconfig(self):
                return ('192.168.4.1', '255.255.255.0', '192.168.4.1', '192.168.4.1')

        class Wlan:
            IF_AP = 1

            def __new__(cls, interface):
                return AccessPoint()

        class Network:
            WLAN = Wlan

        class Server:
            def close(self):
                pass

        class Reader:
            def __init__(self, request):
                self.data = request

            async def readline(self):
                index = self.data.find(b'\n')
                if index < 0:
                    value, self.data = self.data, b''
                    return value
                value, self.data = self.data[:index + 1], self.data[index + 1:]
                return value

            async def read(self, size):
                chunk = self.data[:size]
                self.data = self.data[size:]
                return chunk

        class Writer:
            def __init__(self):
                self.parts = []

            def write(self, value):
                self.parts.append(value)

            async def drain(self):
                pass

            def close(self):
                pass

        async def exercise():
            captured = {}
            gate = asyncio.Event()
            original_network = wifi_recovery.network
            original_start_server = wifi_recovery.asyncio.start_server
            original_sleep = wifi_recovery.asyncio.sleep

            async def fake_start_server(handler, *args, **kwargs):
                captured['handler'] = handler
                return Server()

            async def blocked_sleep(delay):
                if delay == 0:
                    await original_sleep(0)
                    return
                await gate.wait()

            async def request(raw):
                writer = Writer()
                await captured['handler'](Reader(raw), writer)
                return b''.join(writer.parts).decode()

            wifi_recovery.network = Network
            wifi_recovery.asyncio.start_server = fake_start_server
            wifi_recovery.asyncio.sleep = blocked_sleep
            verifier = credential_security.password_verifier(
                'Console-Ash-82!Stone', bytes(range(16))
            )
            task = asyncio.create_task(wifi_recovery.serve_core_recovery(
                'IoT-MD-Recovery-test', 'recovery-ap-password', verifier, 'app failed',
                lambda: None, lambda: None
            ))
            try:
                await original_sleep(0)
                unauthorized = await request(b'GET / HTTP/1.1\r\n\r\n')
                self.assertIn('401 Unauthorized', unauthorized)
                self.assertIn('dedicated recovery password', unauthorized)

                body = b'password=Console-Ash-82%21Stone'
                login = await request(
                    b'POST /login HTTP/1.1\r\nContent-Length: ' +
                    str(len(body)).encode() + b'\r\n\r\n' + body
                )
                self.assertIn('303 See Other', login)
                cookie = next(
                    line for line in login.split('\r\n')
                    if line.startswith('Set-Cookie: iotmd_recovery=')
                )
                session = cookie.split('iotmd_recovery=', 1)[1].split(';', 1)[0]

                page = await request(
                    ('GET / HTTP/1.1\r\nCookie: iotmd_recovery=' + session +
                     '\r\n\r\n').encode()
                )
                self.assertIn('200 OK', page)
                self.assertIn('IoT-MD core recovery', page)

                bad_csrf = b'csrf=wrong'
                rejected = await request(
                    ('POST /retry HTTP/1.1\r\nCookie: iotmd_recovery=' + session +
                     '\r\nContent-Length: ' + str(len(bad_csrf)) +
                     '\r\n\r\n').encode() + bad_csrf
                )
                self.assertIn('403 Forbidden', rejected)
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                wifi_recovery.network = original_network
                wifi_recovery.asyncio.start_server = original_start_server
                wifi_recovery.asyncio.sleep = original_sleep

        asyncio.run(exercise())

    def test_release_client_requires_https(self):
        self.assertEqual(
            release_update._parse_https_url('https://updates.example:8443/latest.json'),
            ('updates.example', 8443, '/latest.json')
        )
        with self.assertRaisesRegex(ValueError, 'must use HTTPS'):
            release_update._parse_https_url('http://updates.example/latest.json')

    def test_release_channel_supports_query_and_static_url_templates(self):
        self.assertEqual(
            release_update.release_manifest_request_url(
                'https://updates.example/latest.json', 'stable'
            ),
            'https://updates.example/latest.json?channel=stable'
        )
        self.assertEqual(
            release_update.release_manifest_request_url(
                'https://updates.example/{channel}/latest.json', 'beta'
            ),
            'https://updates.example/beta/latest.json'
        )
        self.assertEqual(
            release_update.release_manifest_request_url(
                'https://updates.example/{channel}/latest.json', 'rc'
            ),
            'https://updates.example/rc/latest.json'
        )
        application_source = (Path(self.previous_cwd) / 'iotmd.py').read_text()
        self.assertIn("{'log': 'Checking ' + request_url, 'force': True}", application_source)
        self.assertIn("release_check_status + ' — ' + request_url", application_source)

    def test_portal_restarts_use_hardware_timer(self):
        application_source = (Path(self.previous_cwd) / 'iotmd.py').read_text()
        self.assertIn('scheduled_control_timer = Timer(-1)', application_source)
        self.assertIn('mode=Timer.ONE_SHOT', application_source)
        self.assertIn("mark_restart_required('Module configuration changed')", application_source)
        self.assertIn("schedule_hardware_reset('portal_requested_reboot')", application_source)
        self.assertIn("schedule_hardware_shutdown('portal_requested_shutdown')", application_source)
        self.assertNotIn('async def reboot_with_new_modules', application_source)

    def test_core_shutdown_release_advances_core_api(self):
        self.assertEqual(recovery_boot.CORE_API_VERSION, 9)
        self.assertEqual(update_security.CORE_API_VERSION, 9)

    def test_signed_release_descriptor_detects_metadata_tampering(self):
        descriptor = {
            'format_version': 2, 'target_board': 'esp32-s3',
            'channel': 'stable', 'type': 'application', 'version': '2.0.0',
            'release_sequence': 20000,
            'url': 'https://updates.example/bundles/app.iotapp',
            'size': 123, 'sha256': 'a' * 64, 'minimum_core_api': 6,
            'minimum_config_api': 3, 'maximum_config_api': 3,
            'components': {'runtime': 2, 'modules': {'whes': 3}},
            'notes': 'Production release', 'published_at': '2026-07-20T12:00:00Z',
            'signature_scheme': update_security.SIGNATURE_SCHEME,
        }
        descriptor['signature'] = update_security.sign_manifest(
            'release', descriptor, self.private_key
        )
        self.assertIs(
            update_security.validate_release_descriptor(descriptor, 'stable'), descriptor
        )
        descriptor['notes'] = 'Tampered'
        with self.assertRaisesRegex(ValueError, 'signature verification failed'):
            update_security.validate_release_descriptor(descriptor, 'stable')

    def test_management_suite_catalog_uses_shared_suite_verification_key(self):
        catalog_private_key = bytes(range(33, 65))
        Path(update_security.CATALOG_VERIFICATION_KEY_PATH).write_bytes(
            update_security.public_key_bytes(catalog_private_key)
        )
        descriptor = {
            'format_version': 3, 'target_board': 'esp32-s3',
            'channel': 'stable', 'type': 'application', 'version': '2.3.0',
            'release_sequence': 23000,
            'url': 'https://updates.example/bundles/application-2.3.0.iotapp',
            'size': 123, 'sha256': 'b' * 64, 'minimum_core_api': 9,
            'minimum_config_api': 3, 'maximum_config_api': 3,
            'components': {'runtime': 59, 'modules': {}},
            'notes': 'Imported and verified by the management suite',
            'published_at': '2026-08-29T10:00:00Z',
            'signature_scheme': update_security.SIGNATURE_SCHEME,
        }
        descriptor['signature'] = update_security.sign_manifest(
            'release-catalog', descriptor, catalog_private_key
        )
        self.assertIs(
            update_security.validate_release_descriptor(descriptor, 'stable'), descriptor
        )
        Path(update_security.CATALOG_VERIFICATION_KEY_PATH).unlink()
        with self.assertRaisesRegex(ValueError, 'Management Suite verification key'):
            update_security.validate_release_descriptor(descriptor, 'stable')

    def test_static_release_publisher_creates_signed_channel_tree(self):
        source = Path('source.py')
        source.write_text('VALUE=1')
        build_bundle(
            Path('universal.iotapp'), '2.0.0', [('iotmd.py', source)],
            signing_key=self.private_key, release_sequence=20000
        )
        descriptor_path, bundle_path, descriptor = publish_release(
            'universal.iotapp', 'site', 'https://updates.example/iotmd',
            'stable', self.private_key, 'Production release',
            '2026-07-20T12:00:00Z'
        )
        self.assertEqual(descriptor_path, Path('site/stable/latest.json').resolve())
        self.assertTrue(bundle_path.is_file())
        self.assertEqual(descriptor['release_sequence'], 20000)
        self.assertEqual(descriptor['type'], 'application')
        update_security.validate_release_descriptor(descriptor, 'stable')
        channel = json.loads(descriptor_path.read_text())
        self.assertEqual(len(channel['releases']), 1)
        self.assertEqual(
            release_update.release_descriptors(channel, 'stable'),
            (descriptor,),
        )

    def test_release_notes_include_signed_source_revision(self):
        revision = '1' * 40
        notes = notes_with_source('RC1 hardening', revision)
        self.assertEqual(notes, 'RC1 hardening | Source: ' + revision)
        with self.assertRaisesRegex(ValueError, 'source revision is invalid'):
            notes_with_source('RC1', 'short')

    def test_channel_keeps_application_and_firmware_available_together(self):
        source = Path('source.py')
        source.write_text('VALUE=1')
        build_bundle(
            Path('application.iotapp'), '2.1.0-beta.1',
            [('iotmd.py', source)], signing_key=self.private_key,
            release_sequence=20100,
        )
        image = Path('micropython.bin')
        image.write_bytes(b'\xe9' + (b'\0' * 127))
        build_firmware_bundle(
            image, Path('firmware.iotcore'), 'core-2.1.0-beta.1',
            signing_key=self.private_key, release_sequence=20100,
        )
        publish_release(
            'application.iotapp', 'site', 'https://updates.example/iotmd',
            'beta', self.private_key, 'Application', '2026-07-20T12:00:00Z',
        )
        publish_release(
            'firmware.iotcore', 'site', 'https://updates.example/iotmd',
            'beta', self.private_key, 'Firmware', '2026-07-20T12:00:00Z',
        )

        channel = json.loads(Path('site/beta/latest.json').read_text())
        releases = release_update.release_descriptors(channel, 'beta')
        self.assertEqual(channel['type'], 'application')
        self.assertEqual(
            {release['type'] for release in releases},
            {'application', 'firmware'},
        )
        self.assertEqual(
            release_update.select_release(releases, 20099, 20099)['type'],
            'firmware',
        )
        self.assertEqual(
            release_update.select_release(releases, 20099, 20100)['type'],
            'application',
        )
        self.assertIsNone(
            release_update.select_release(releases, 20100, 20100)
        )

        channel['releases'][0]['notes'] = 'Tampered'
        with self.assertRaisesRegex(ValueError, 'signature verification failed'):
            release_update.release_descriptors(channel, 'beta')

    def test_incompatible_application_does_not_block_required_core_release(self):
        common = {
            'format_version': 2, 'target_board': 'esp32-s3',
            'channel': 'beta', 'release_sequence': 20200,
            'size': 128, 'sha256': 'a' * 64,
            'minimum_config_api': 3, 'maximum_config_api': 3,
            'notes': 'Paired release', 'published_at': '2026-08-15T12:00:00Z',
            'signature_scheme': update_security.SIGNATURE_SCHEME,
        }
        application = dict(common, **{
            'type': 'application', 'version': '2.2.0',
            'url': 'https://updates.example/app.iotapp', 'minimum_core_api': 7,
            'components': {'runtime': 3, 'modules': {'whes': 4}},
        })
        firmware = dict(common, **{
            'type': 'firmware', 'version': 'core-2.2.0',
            'url': 'https://updates.example/core.iotcore', 'minimum_core_api': 6,
        })
        for descriptor in (application, firmware):
            descriptor['signature'] = update_security.sign_manifest(
                'release', descriptor, self.private_key
            )
        channel = dict(application)
        channel['releases'] = [application, firmware]

        with patch.object(recovery_boot, 'CORE_API_VERSION', 6):
            releases = release_update.release_descriptors(channel, 'beta')
            self.assertEqual(
                release_update.select_release(releases, 20100, 20100)['type'],
                'firmware'
            )
        with patch.object(recovery_boot, 'CORE_API_VERSION', 7):
            self.assertEqual(
                release_update.select_release(releases, 20100, 20200)['type'],
                'application'
            )

    def test_publisher_removes_only_output_root_staging_bundle(self):
        output = Path('site')
        output.mkdir()
        source = Path('source.py')
        source.write_text('VALUE=1')
        staged = output / 'staged.iotapp'
        build_bundle(
            staged, '2.2.0-beta.1', [('iotmd.py', source)],
            signing_key=self.private_key, release_sequence=20200,
        )

        _descriptor_path, published, _descriptor = publish_release(
            staged, output, 'https://updates.example/iotmd', 'beta',
            self.private_key, 'Staged release', '2026-07-20T12:00:00Z',
        )
        self.assertFalse(staged.exists())
        self.assertTrue(published.is_file())

        external = Path('external.iotapp')
        build_bundle(
            external, '2.2.0-beta.2', [('iotmd.py', source)],
            signing_key=self.private_key, release_sequence=20201,
        )
        publish_release(
            external, output, 'https://updates.example/iotmd', 'beta',
            self.private_key, 'External release', '2026-07-20T12:00:00Z',
        )
        self.assertTrue(external.is_file())

    def test_chunked_release_reader_decodes_stream(self):
        class AsyncBuffer:
            def __init__(self, data):
                self.data = data

            async def read(self, size):
                chunk = self.data[:size]
                self.data = self.data[size:]
                return chunk

            async def readline(self):
                index = self.data.find(b'\n')
                if index < 0:
                    chunk, self.data = self.data, b''
                    return chunk
                chunk = self.data[:index + 1]
                self.data = self.data[index + 1:]
                return chunk

        async def exercise():
            reader = release_update._ChunkedReader(AsyncBuffer(
                b'4\r\nWiki\r\n5\r\npedia\r\n0\r\nX-Test: yes\r\n\r\n'
            ))
            output = bytearray()
            while True:
                chunk = await reader.read(3)
                if not chunk:
                    break
                output.extend(chunk)
            return bytes(output)

        self.assertEqual(asyncio.run(exercise()), b'Wikipedia')

    def test_remote_stage_verifies_signed_bundle_hash_and_sequence(self):
        payload = b'IoTMD bundle bytes'
        descriptor = {
            'format_version': 2, 'target_board': 'esp32-s3',
            'channel': 'beta', 'type': 'application', 'version': '2.1.0-beta.1',
            'release_sequence': 20100,
            'url': 'https://updates.example/bundles/app.iotapp',
            'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(),
            'minimum_core_api': 6, 'minimum_config_api': 3,
            'maximum_config_api': 3,
            'components': {'runtime': 2, 'modules': {'whes': 3}}, 'notes': 'Beta',
            'published_at': '2026-07-20T12:00:00Z',
            'signature_scheme': update_security.SIGNATURE_SCHEME,
        }
        descriptor['signature'] = update_security.sign_manifest(
            'release', descriptor, self.private_key
        )

        class AsyncBuffer:
            def __init__(self, data):
                self.data = data

            async def read(self, size):
                chunk = self.data[:size]
                self.data = self.data[size:]
                return chunk

        class Writer:
            def close(self):
                return None

        async def open_response(*args):
            return AsyncBuffer(payload), Writer(), len(payload)

        async def receive(reader, length, allow_protected, maximum, progress_callback=None):
            received = bytearray()
            while len(received) < length:
                received.extend(await reader.read(length - len(received)))
            self.assertEqual(bytes(received), payload)
            return {'status': 'ready', 'version': '2.1.0-beta.1', 'release_sequence': 20100}

        with patch.object(release_update, '_open_response', side_effect=open_response):
            state = asyncio.run(release_update.stage_release(
                descriptor, 'ca.der', receive, None
            ))
        self.assertEqual(state['release_sequence'], 20100)


if __name__ == '__main__':
    unittest.main()
