import tempfile
import unittest
from pathlib import Path

import fleet_management
import update_security


class FleetManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.private_key = bytes(range(1, 33))
        self.key_path = Path(self.temp.name) / 'verify.key'
        self.key_path.write_bytes(update_security.public_key_bytes(self.private_key))
        self.state_path = str(Path(self.temp.name) / 'fleet.json')
        self.now = 2000000000

    def tearDown(self):
        self.temp.cleanup()

    def policy(self, sequence=1, target_device='device-1', target_cohort=''):
        value = {
            'format_version': 1,
            'target_board': 'esp32-s3',
            'policy_sequence': sequence,
            'issued_at': self.now - 60,
            'not_before': self.now - 10,
            'expires_at': self.now + 3600,
            'target_device': target_device,
            'target_cohort': target_cohort,
            'maintenance': {
                'weekdays': [2], 'start_minute': 600, 'duration_minutes': 60,
            },
            'updates': {
                'channel': 'alpha', 'automatic_download': True,
                'automatic_activation': True, 'maximum_consecutive_failures': 2,
            },
            'telemetry': {
                'enabled': True, 'minimum_interval_s': 60,
                'severities': ['warning', 'error', 'critical'],
            },
            'commands': [
                {'id': 'command-1', 'action': 'check-update', 'release_sequence': 0}
            ],
            'signature_scheme': update_security.SIGNATURE_SCHEME,
        }
        value['signature'] = update_security.sign_manifest(
            'fleet-policy', value, self.private_key
        )
        return value

    def service(self):
        return fleet_management.FleetService(
            'device-1', 'test', self.state_path, str(self.key_path),
            now=lambda: self.now,
            localtime=lambda _epoch: (2033, 5, 18, 10, 30, 0, 2, 138),
        )

    def test_applies_signed_targeted_policy_and_exposes_command(self):
        service = self.service()
        snapshot = service.apply_policy(self.policy())

        self.assertEqual(snapshot['policy_sequence'], 1)
        self.assertTrue(snapshot['within_maintenance_window'])
        self.assertEqual(snapshot['pending_commands'][0]['id'], 'command-1')

        service.complete_command('command-1', 'complete')
        self.assertEqual(service.pending_commands(), [])

    def test_rejects_stale_tampered_and_wrong_target_policies(self):
        service = self.service()
        service.apply_policy(self.policy())
        with self.assertRaisesRegex(ValueError, 'not newer'):
            service.apply_policy(self.policy())

        tampered = self.policy(2)
        tampered['updates']['automatic_activation'] = False
        with self.assertRaisesRegex(ValueError, 'signature'):
            service.apply_policy(tampered)

        with self.assertRaisesRegex(ValueError, 'target'):
            service.apply_policy(self.policy(2, target_device='someone-else'))

    def test_failure_threshold_pauses_rollout_and_success_clears_it(self):
        service = self.service()
        service.apply_policy(self.policy())
        service.record_result('failed', 'one')
        self.assertFalse(service.snapshot()['rollout_paused'])
        service.record_result('failed', 'two')
        self.assertTrue(service.snapshot()['rollout_paused'])
        service.record_result('healthy')
        self.assertFalse(service.snapshot()['rollout_paused'])


if __name__ == '__main__':
    unittest.main()
