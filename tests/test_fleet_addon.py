import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

import update_security


class FleetAddonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get('HAMD_FLEET_DATA')
        os.environ['HAMD_FLEET_DATA'] = self.temp.name
        path = (
            Path(__file__).resolve().parents[1] /
            'home_assistant_addons/hamd_fleet/rootfs/app/fleet_app.py'
        )
        spec = importlib.util.spec_from_file_location('hamd_fleet_test', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def tearDown(self):
        if self.previous is None:
            os.environ.pop('HAMD_FLEET_DATA', None)
        else:
            os.environ['HAMD_FLEET_DATA'] = self.previous
        self.temp.cleanup()

    def policy(self):
        return {
            'format_version': 1, 'target_board': 'esp32-s3', 'policy_sequence': 1,
            'issued_at': 2000000000, 'not_before': 1999999999,
            'expires_at': 2000003600, 'target_device': 'device-1',
            'target_cohort': '',
            'maintenance': {
                'weekdays': [0, 1, 2, 3, 4, 5, 6],
                'start_minute': 120, 'duration_minutes': 60,
            },
            'updates': {
                'channel': 'alpha', 'automatic_download': True,
                'automatic_activation': False,
                'maximum_consecutive_failures': 2,
            },
            'telemetry': {
                'enabled': True, 'minimum_interval_s': 60,
                'severities': ['warning', 'error', 'critical'],
            },
            'commands': [],
        }

    def test_addon_signature_verifies_with_device_implementation(self):
        signed = self.module.SIGNER.sign(self.policy())
        public = self.module.PUBLIC_KEY_PATH.read_bytes()
        point = (
            update_security._bytes_to_int(public[:32]),
            update_security._bytes_to_int(public[32:]),
        )
        self.assertTrue(update_security.verify_manifest_signature(
            'fleet-policy', signed, signed['signature'], point
        ))
        self.assertNotEqual(
            self.module.SIGNING_KEY_PATH.read_bytes(),
            self.module.PUBLIC_KEY_PATH.read_bytes()
        )

    def test_registered_device_response_hides_certificate_paths(self):
        store = self.module.FleetStore(Path(self.temp.name) / 'state.json')
        result = store.register({
            'id': 'device-1', 'host': 'device.local',
            'ca_path': '/ssl/ca.pem', 'cert_path': '/ssl/client.pem',
            'key_path': '/ssl/client-key.pem',
        })
        self.assertNotIn('key_path', result)
        self.assertNotIn('cert_path', result)
        self.assertEqual(result['host'], 'device.local')

    def test_rollout_advances_by_cohort_and_stops_at_failure_threshold(self):
        store = self.module.FleetStore(Path(self.temp.name) / 'rollout.json')
        for identifier, cohort in (('canary-1', 'canary'), ('main-1', 'main')):
            store.register({
                'id': identifier, 'host': identifier + '.local', 'cohort': cohort,
                'ca_path': '/ssl/ca.pem', 'cert_path': '/ssl/client.pem',
                'key_path': '/ssl/client-key.pem',
            })
        rollout = store.create_rollout({
            'release_sequence': 2101, 'cohorts': ['canary', 'main'],
            'maximum_failures': 1,
        })
        store.record_rollout_result(rollout['id'], 'canary-1', 'complete')
        advanced = store.advance_rollout(rollout['id'])
        self.assertEqual(advanced['cohort_index'], 1)
        stopped = store.record_rollout_result(
            rollout['id'], 'main-1', 'failed', 'health gate failed'
        )
        self.assertEqual(stopped['status'], 'stopped')
        with self.assertRaisesRegex(ValueError, 'stopped'):
            store.advance_rollout(rollout['id'])


if __name__ == '__main__':
    unittest.main()
