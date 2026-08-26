import asyncio
import os
import tempfile
import unittest
from pathlib import Path

import app_update
import application_upload
import update_security
import update_support
from services.update_service import _ArtifactReader
from tools.build_update import build_bundle


class ApplicationUploadTests(unittest.TestCase):
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

    def bundle(self):
        Path('entry.py').write_text('VALUE = 1\n')
        Path('settings.json').write_text('{}\n')
        build_bundle(
            Path('resumable.part'), '2.2.1',
            [('iotmd.py', Path('entry.py')), ('app_settings.json', Path('settings.json'))],
            signing_key=self.private_key, release_sequence=2401,
            minimum_core_api=1, components={'runtime': 1, 'modules': {}},
        )
        return Path('resumable.part')

    def test_file_backed_portal_upload_is_adopted_without_second_copy(self):
        artifact = self.bundle()
        reader = _ArtifactReader(artifact)
        message = asyncio.run(application_upload.receive_for_portal(
            reader, artifact.stat().st_size, False, 2 * 1024 * 1024
        ))
        reader.close()

        self.assertIn('2.2.1', message)
        self.assertFalse(artifact.exists())
        self.assertTrue(Path(app_update.BUNDLE_PATH).exists())
        self.assertFalse(Path(app_update.BUNDLE_PATH + '.upload').exists())
        self.assertEqual(app_update.update_status()['status'], 'ready')

    def test_rejected_adopted_bundle_does_not_leave_pending_state(self):
        artifact = self.bundle()
        payload = bytearray(artifact.read_bytes())
        payload[-1] ^= 1
        artifact.write_bytes(payload)
        reader = _ArtifactReader(artifact)
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            asyncio.run(application_upload.receive_for_portal(
                reader, len(payload), False, 2 * 1024 * 1024
            ))
        reader.close()

        self.assertTrue(artifact.exists())
        self.assertFalse(Path(app_update.BUNDLE_PATH).exists())
        self.assertEqual(app_update.update_status()['status'], 'idle')


if __name__ == '__main__':
    unittest.main()
