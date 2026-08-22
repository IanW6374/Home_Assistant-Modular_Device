import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import recovery_boot
import update_orchestrator
import update_security


class UpdateOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'paired.json')
        self.private_key = bytes(range(1, 33))

    def tearDown(self):
        self.temp.cleanup()

    def release(self, kind, sequence=20):
        value = {
            'format_version': 2,
            'target_board': 'esp32-s3',
            'channel': 'beta',
            'type': kind,
            'version': ('core-' if kind == 'firmware' else '') + '2.0.0',
            'release_sequence': sequence,
            'url': 'https://updates.example/' + kind,
            'size': 100,
            'sha256': 'a' * 64,
            'minimum_core_api': 1,
            'minimum_config_api': 1,
            'maximum_config_api': 99,
            'notes': 'paired',
            'published_at': '2026-08-16T12:00:00Z',
            'signature_scheme': update_security.SIGNATURE_SCHEME,
        }
        if kind == 'application':
            value['components'] = {'runtime': 1, 'modules': {}}
        value['signature'] = update_security.sign_manifest(
            'release', value, self.private_key
        )
        return value

    def test_firmware_is_first_then_application_resumes(self):
        releases = [self.release('application'), self.release('firmware')]
        with patch.object(update_security, 'validate_release_descriptor', return_value=True):
            state = update_orchestrator.begin(
                releases, 10, 10, '1.0.0', 'core-1.0.0', self.path
            )
            self.assertEqual(state['active_type'], 'firmware')
            self.assertEqual(update_orchestrator.status(self.path)['step'], 1)
            update_orchestrator.mark_staged(releases[1], self.path)
            update_orchestrator.mark_activating('firmware', self.path)

            resumed = update_orchestrator.refresh(
                10, 20, '1.0.0', 'core-2.0.0', self.path
            )
            self.assertEqual(resumed['active_type'], 'application')
            self.assertEqual(update_orchestrator.status(self.path)['step'], 2)

            completed = update_orchestrator.refresh(
                20, 20, '2.0.0', 'core-2.0.0', self.path
            )
            self.assertEqual(completed['status'], 'complete')
            self.assertFalse(Path(self.path).exists())


if __name__ == '__main__':
    unittest.main()
