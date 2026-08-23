import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_update
import firmware_update
import universal_update
import update_security
import update_support
from tools.build_firmware_update import build_firmware_bundle
from tools.build_universal_update import build_universal_bundle
from tools.build_update import build_bundle


class AsyncReader:
    def __init__(self, payload):
        self.payload = bytes(payload)

    async def read(self, size):
        chunk = self.payload[:size]
        self.payload = self.payload[size:]
        return chunk


class UniversalUpdateTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)
        self.private_key = bytes(range(1, 33))
        Path(update_security.VERIFICATION_KEY_PATH).write_bytes(
            update_security.public_key_bytes(self.private_key)
        )

    def tearDown(self):
        update_support.release_update_lock()
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def package(self, firmware_payload=b'firmware bundle', application_payload=b'application bundle'):
        sequence = 40
        manifest = {
            'format_version': 2,
            'target_board': 'esp32-s3',
            'version': '2.0.0',
            'release_sequence': sequence,
            'firmware': {
                'version': '2.0.0',
                'release_sequence': sequence,
                'size': len(firmware_payload),
                'sha256': hashlib.sha256(firmware_payload).hexdigest(),
            },
            'application': {
                'version': '2.0.0',
                'release_sequence': sequence,
                'size': len(application_payload),
                'sha256': hashlib.sha256(application_payload).hexdigest(),
            },
            'activation_order': ['application', 'firmware'],
            'maintenance_required': True,
            'rollback_policy': 'paired',
            'trial_timeout_s': 180,
            'signature_scheme': update_security.SIGNATURE_SCHEME,
        }
        manifest['signature'] = update_security.sign_manifest(
            'hamu', manifest, self.private_key
        )
        encoded = json.dumps(manifest, separators=(',', ':')).encode()
        return (
            universal_update.MAGIC + len(encoded).to_bytes(4, 'big') + encoded +
            firmware_payload + application_payload
        )

    def test_streaming_receiver_stages_core_then_application(self):
        payload = self.package()
        calls = []
        progress = []

        async def firmware_receiver(reader, length, maximum, progress_callback=None):
            calls.append('firmware')
            data = await reader.read(length)
            await progress_callback('writing', length, length)
            await progress_callback('verification', length, length)
            self.assertEqual(data, b'firmware bundle')
            return {
                'version': '2.0.0',
                'release_sequence': 40,
            }

        async def application_receiver(
            reader, length, allow_protected, maximum, progress_callback=None
        ):
            calls.append('application')
            data = await reader.read(length)
            await progress_callback('verification', length, length)
            self.assertEqual(data, b'application bundle')
            return {'version': '2.0.0', 'release_sequence': 40}

        state = asyncio.run(universal_update.receive_bundle(
            AsyncReader(payload), len(payload),
            firmware_receiver=firmware_receiver,
            application_receiver=application_receiver,
            progress_callback=lambda *values: progress.append(values),
        ))

        self.assertEqual(calls, ['firmware', 'application'])
        self.assertEqual(state['status'], 'ready')
        self.assertEqual(universal_update.update_status()['version'], '2.0.0')
        self.assertIn('firmware_writing', [entry[0] for entry in progress])
        self.assertIn('firmware_verification', [entry[0] for entry in progress])
        self.assertIn('application_verification', [entry[0] for entry in progress])

    def test_outer_signature_and_component_hashes_are_enforced(self):
        payload = bytearray(self.package())
        payload[-1] ^= 1

        async def firmware_receiver(reader, length, maximum, progress_callback=None):
            await reader.read(length)
            return {
                'version': '2.0.0',
                'release_sequence': 40,
            }

        async def application_receiver(
            reader, length, allow_protected, maximum, progress_callback=None
        ):
            await reader.read(length)
            return {'version': '2.0.0', 'release_sequence': 40}

        with patch.object(firmware_update, 'discard_pending_update') as discard:
            with self.assertRaisesRegex(ValueError, 'application bundle SHA-256'):
                asyncio.run(universal_update.receive_bundle(
                    AsyncReader(payload), len(payload),
                    firmware_receiver=firmware_receiver,
                    application_receiver=application_receiver,
                ))
            discard.assert_called_once()

        original = self.package()
        manifest_size = int.from_bytes(original[6:10], 'big')
        manifest = json.loads(original[10:10 + manifest_size].decode())
        manifest['signature'] = '0' * 128
        encoded = json.dumps(manifest, separators=(',', ':')).encode()
        altered = (
            universal_update.MAGIC + len(encoded).to_bytes(4, 'big') + encoded +
            original[10 + manifest_size:]
        )
        with self.assertRaisesRegex(ValueError, 'signature verification failed'):
            asyncio.run(universal_update.receive_bundle(
                AsyncReader(altered), len(altered),
                firmware_receiver=firmware_receiver,
                application_receiver=application_receiver,
            ))

    def test_activation_selects_both_trials(self):
        Path(universal_update.STATE_PATH).write_text(json.dumps({
            'status': 'ready', 'version': '2.0.0',
            'application_sequence': 40, 'firmware_sequence': 40,
        }))
        with (
            patch.object(app_update, 'update_status', return_value={'status': 'ready'}),
            patch.object(firmware_update, 'update_status', return_value={'status': 'ready'}),
            patch.object(app_update, 'configure_pending_update') as configure,
            patch.object(firmware_update, 'activate_pending') as activate,
        ):
            state = universal_update.activate_pending()
        configure.assert_called_once_with({})
        activate.assert_called_once_with()
        self.assertEqual(state['status'], 'activating')

    def test_activation_enforces_signed_maintenance_and_trial_timeout(self):
        Path(universal_update.STATE_PATH).write_text(json.dumps({
            'status': 'ready', 'version': '2.0.0',
            'application_sequence': 40, 'firmware_sequence': 40,
            'application_required': True, 'firmware_required': True,
            'activation_order': ['firmware', 'application'],
            'maintenance_required': True, 'trial_timeout_s': 420,
        }))
        with self.assertRaisesRegex(ValueError, 'maintenance window'):
            universal_update.activate_pending(False)
        calls = []
        with (
            patch.object(app_update, 'update_status', return_value={'status': 'ready'}),
            patch.object(firmware_update, 'update_status', return_value={'status': 'ready'}),
            patch.object(app_update, 'configure_pending_update', side_effect=lambda _: calls.append('application')),
            patch.object(firmware_update, 'activate_pending', side_effect=lambda: calls.append('firmware')),
        ):
            universal_update.activate_pending(True)
        self.assertEqual(calls, ['firmware', 'application'])
        self.assertEqual(universal_update.trial_timeout_ms(), 420000)

    def test_matching_installed_core_is_verified_but_not_staged(self):
        payload = self.package()
        calls = []

        async def firmware_receiver(*args, **kwargs):
            calls.append('firmware')

        async def application_receiver(
            reader, length, allow_protected, maximum, progress_callback=None
        ):
            calls.append('application')
            await reader.read(length)
            return {'version': '2.0.0', 'release_sequence': 40}

        with (
            patch.object(firmware_update, 'running_release_sequence', return_value=40),
            patch.object(app_update, 'running_release_sequence', return_value=39),
        ):
            state = asyncio.run(universal_update.receive_bundle(
                AsyncReader(payload), len(payload),
                firmware_receiver=firmware_receiver,
                application_receiver=application_receiver,
            ))

        self.assertEqual(calls, ['application'])
        self.assertFalse(state['firmware_required'])
        self.assertTrue(state['application_required'])

        with (
            patch.object(app_update, 'update_status', return_value={'status': 'ready'}),
            patch.object(firmware_update, 'update_status', return_value={'status': 'idle'}),
            patch.object(app_update, 'configure_pending_update') as configure,
            patch.object(firmware_update, 'activate_pending') as activate,
        ):
            universal_update.activate_pending()
        configure.assert_called_once_with({})
        activate.assert_not_called()

    def test_builder_binds_two_independently_signed_bundles(self):
        source = Path('source.py')
        source.write_text('VALUE = 1')
        settings = Path('settings.json')
        settings.write_text('{}')
        build_bundle(
            Path('application.hamd'), '2.0.0',
            [('HA-Device.py', source), ('app_settings.json', settings)],
            signing_key=self.private_key, release_sequence=40,
            minimum_core_api=1,
            components={'runtime': 1, 'modules': {}},
        )
        image = Path('micropython.bin')
        image.write_bytes(b'\xe9' + b'core image' * 20)
        build_firmware_bundle(
            image, Path('firmware.hamf'), '2.0.0',
            signing_key=self.private_key, release_sequence=40,
            minimum_core_api=1,
        )
        manifest = build_universal_bundle(
            Path('universal.hamu'), Path('application.hamd'), Path('firmware.hamf'),
            '2.0.0', 40, self.private_key
        )
        self.assertEqual(manifest['application']['release_sequence'], 40)
        self.assertEqual(manifest['firmware']['release_sequence'], 40)
        self.assertEqual(manifest['format_version'], 2)
        self.assertEqual(manifest['rollback_policy'], 'paired')
        with Path('universal.hamu').open('rb') as stream:
            self.assertEqual(stream.read(6), universal_update.MAGIC)
            length = int.from_bytes(stream.read(4), 'big')
            stored = json.loads(stream.read(length).decode())
        public = update_security.public_key_bytes(self.private_key)
        point = (
            update_security._bytes_to_int(public[:32]),
            update_security._bytes_to_int(public[32:]),
        )
        self.assertTrue(update_security.verify_manifest_signature(
            'hamu', stored, stored['signature'], point
        ))

    def test_builder_can_create_v1_bootstrap_bundle_for_v1_9_loader(self):
        source = Path('source.py')
        source.write_text('VALUE = 1')
        settings = Path('settings.json')
        settings.write_text('{}')
        build_bundle(
            Path('application.hamd'), '2.0.0-alpha.1',
            [('HA-Device.py', source), ('app_settings.json', settings)],
            signing_key=self.private_key, release_sequence=2101,
            minimum_core_api=1, components={'runtime': 1, 'modules': {}},
        )
        image = Path('micropython.bin')
        image.write_bytes(b'\xe9' + b'core image' * 20)
        build_firmware_bundle(
            image, Path('firmware.hamf'), '2.0.0-alpha.1',
            signing_key=self.private_key, release_sequence=2101,
            minimum_core_api=1,
        )
        manifest = build_universal_bundle(
            Path('bootstrap.hamu'), Path('application.hamd'),
            Path('firmware.hamf'), '2.0.0-alpha.1', 2101,
            self.private_key, format_version=1,
        )
        self.assertEqual(manifest['format_version'], 1)
        self.assertNotIn('activation_order', manifest)
        self.assertNotIn('maintenance_required', manifest)
        update_security.validate_universal_manifest(manifest)


if __name__ == '__main__':
    unittest.main()
