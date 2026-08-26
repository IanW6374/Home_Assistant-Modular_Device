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
import universal_upload
import update_security


class UniversalUploadTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)
        self.private_key = bytes(range(1, 33))
        Path(update_security.VERIFICATION_KEY_PATH).write_bytes(
            update_security.public_key_bytes(self.private_key)
        )

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def manifest(self, format_version=3):
        manifest = {
            'format_version': format_version,
            'target_board': 'esp32-s3',
            'version': '2.2.1',
            'release_sequence': 2401,
            'firmware': {
                'version': '2.2.1', 'release_sequence': 2401,
                'size': 1400000,
                'sha256': hashlib.sha256(b'firmware').hexdigest(),
            },
            'application': {
                'version': '2.2.1', 'release_sequence': 2401,
                'size': 420000,
                'sha256': hashlib.sha256(b'application').hexdigest(),
            },
            'activation_order': ['application', 'firmware'],
            'maintenance_required': True,
            'rollback_policy': 'paired',
            'trial_timeout_s': 180,
            'signature_scheme': update_security.SIGNATURE_SCHEME,
        }
        manifest['signature'] = update_security.sign_manifest(
            'iotuni', manifest, self.private_key
        )
        return manifest

    def test_sequential_plan_binds_both_exact_inner_uploads(self):
        manifest = self.manifest()
        with (
            patch.object(app_update, 'running_release_sequence', return_value=2400),
            patch.object(firmware_update, 'running_release_sequence', return_value=2400),
            patch.object(app_update, 'update_status', return_value={'status': 'idle'}),
            patch.object(firmware_update, 'update_status', return_value={'status': 'idle'}),
            patch.object(universal_update, 'update_status', return_value={'status': 'idle'}),
        ):
            plan = universal_upload.prepare(manifest)

        self.assertTrue(plan['application']['required'])
        self.assertTrue(plan['firmware']['required'])
        for kind in ('firmware', 'application'):
            component = manifest[kind]
            request = {
                'universal_plan': plan['id'],
                'id': 'upload-' + kind,
                'kind': kind,
                'total_bytes': component['size'],
                'sha256': component['sha256'],
            }
            self.assertTrue(universal_upload.authorize_upload(request))

        stored = json.loads(Path(universal_upload.PLAN_PATH).read_text())
        self.assertEqual(stored['firmware']['upload_id'], 'upload-firmware')
        self.assertEqual(stored['application']['upload_id'], 'upload-application')

    def test_upload_must_match_signed_size_and_digest(self):
        manifest = self.manifest()
        with (
            patch.object(app_update, 'running_release_sequence', return_value=2400),
            patch.object(firmware_update, 'running_release_sequence', return_value=2400),
            patch.object(app_update, 'update_status', return_value={'status': 'idle'}),
            patch.object(firmware_update, 'update_status', return_value={'status': 'idle'}),
            patch.object(universal_update, 'update_status', return_value={'status': 'idle'}),
        ):
            plan = universal_upload.prepare(manifest)
        request = {
            'universal_plan': plan['id'], 'id': 'upload-firmware',
            'kind': 'firmware', 'total_bytes': manifest['firmware']['size'],
            'sha256': '0' * 64,
        }
        with self.assertRaisesRegex(ValueError, 'does not match'):
            universal_upload.authorize_upload(request)
        request['sha256'] = manifest['firmware']['sha256']
        request['total_bytes'] += 1
        with self.assertRaisesRegex(ValueError, 'size does not match'):
            universal_upload.authorize_upload(request)

    def test_completed_components_are_paired_only_after_installer_metadata_matches(self):
        manifest = self.manifest()
        with (
            patch.object(app_update, 'running_release_sequence', return_value=2400),
            patch.object(firmware_update, 'running_release_sequence', return_value=2400),
            patch.object(app_update, 'update_status', return_value={'status': 'idle'}),
            patch.object(firmware_update, 'update_status', return_value={'status': 'idle'}),
            patch.object(universal_update, 'update_status', return_value={'status': 'idle'}),
        ):
            plan = universal_upload.prepare(manifest)
        for kind in ('firmware', 'application'):
            component = manifest[kind]
            universal_upload.authorize_upload({
                'universal_plan': plan['id'], 'id': 'upload-' + kind,
                'kind': kind, 'total_bytes': component['size'],
                'sha256': component['sha256'],
            })
        ready = {
            'status': 'ready', 'version': '2.2.1', 'release_sequence': 2401
        }
        with (
            patch.object(firmware_update, 'update_status', return_value=ready),
            patch.object(app_update, 'update_status', return_value=ready),
        ):
            self.assertTrue(universal_upload.mark_complete(
                'upload-firmware', 'firmware'
            ))
            self.assertTrue(universal_upload.mark_complete(
                'upload-application', 'application'
            ))
        staged = {'status': 'ready', 'version': '2.2.1'}
        with patch.object(
            universal_update, 'stage_preverified', return_value=staged
        ) as stage:
            result = universal_upload.finalize(plan['id'])
        self.assertEqual(result, staged)
        stage.assert_called_once_with(manifest, True, True)
        self.assertFalse(Path(universal_upload.PLAN_PATH).exists())

    def test_installed_application_is_skipped_for_bridge_core_update(self):
        manifest = self.manifest()
        with (
            patch.object(app_update, 'running_release_sequence', return_value=2401),
            patch.object(firmware_update, 'running_release_sequence', return_value=2400),
            patch.object(firmware_update, 'update_status', return_value={'status': 'idle'}),
            patch.object(universal_update, 'update_status', return_value={'status': 'idle'}),
        ):
            plan = universal_upload.prepare(manifest)
        self.assertFalse(plan['application']['required'])
        self.assertTrue(plan['application']['complete'])
        self.assertTrue(plan['firmware']['required'])

    def test_same_container_resumes_existing_plan_after_component_staging(self):
        manifest = self.manifest()
        with (
            patch.object(app_update, 'running_release_sequence', return_value=2400),
            patch.object(firmware_update, 'running_release_sequence', return_value=2400),
            patch.object(app_update, 'update_status', return_value={'status': 'idle'}),
            patch.object(firmware_update, 'update_status', return_value={'status': 'idle'}),
            patch.object(universal_update, 'update_status', return_value={'status': 'idle'}),
        ):
            plan = universal_upload.prepare(manifest)
        universal_upload.authorize_upload({
            'universal_plan': plan['id'], 'id': 'upload-firmware',
            'kind': 'firmware', 'total_bytes': manifest['firmware']['size'],
            'sha256': manifest['firmware']['sha256'],
        })
        ready = {
            'status': 'ready', 'version': '2.2.1', 'release_sequence': 2401
        }
        with patch.object(firmware_update, 'update_status', return_value=ready):
            universal_upload.mark_complete('upload-firmware', 'firmware')
        with (
            patch.object(firmware_update, 'update_status', return_value=ready),
            patch.object(universal_update, 'update_status', return_value={'status': 'idle'}),
        ):
            resumed = universal_upload.prepare(manifest)
        self.assertTrue(resumed['firmware']['complete'])
        self.assertFalse(resumed['application']['complete'])

    def test_tampered_outer_manifest_is_rejected_before_any_upload(self):
        manifest = self.manifest()
        manifest['application']['size'] += 1
        with self.assertRaisesRegex(ValueError, 'signature'):
            universal_upload.prepare(manifest)
        self.assertFalse(Path(universal_upload.PLAN_PATH).exists())

    def test_newer_installed_component_cannot_be_paired_with_older_release(self):
        manifest = self.manifest()
        with (
            patch.object(app_update, 'running_release_sequence', return_value=2402),
            patch.object(firmware_update, 'running_release_sequence', return_value=2400),
            patch.object(universal_update, 'update_status', return_value={'status': 'idle'}),
            self.assertRaisesRegex(ValueError, 'older than an installed component'),
        ):
            universal_upload.prepare(manifest)

    def test_v3_bridge_validation_works_with_old_public_validator(self):
        manifest = self.manifest()
        with patch.object(
            update_security, 'validate_universal_manifest',
            side_effect=ValueError('unsupported universal update format')
        ):
            result = universal_upload.validate_manifest(manifest)
        self.assertTrue(result['signed'])

    def test_file_backed_receiver_rejects_split_format(self):
        manifest = self.manifest()
        encoded = json.dumps(manifest, separators=(',', ':')).encode()
        payload = (
            universal_update.MAGIC + len(encoded).to_bytes(4, 'big') + encoded +
            b'x' * manifest['firmware']['size'] +
            b'y' * manifest['application']['size']
        )

        import asyncio
        from services.update_service import _ArtifactReader
        Path('format-3.iotuni').write_bytes(payload)
        reader = _ArtifactReader('format-3.iotuni')
        with self.assertRaisesRegex(ValueError, 'sequential component transport'):
            asyncio.run(universal_update.receive_bundle(reader, len(payload)))
        reader.close()


if __name__ == '__main__':
    unittest.main()
