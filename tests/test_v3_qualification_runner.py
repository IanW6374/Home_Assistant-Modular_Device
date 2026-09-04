import json
from pathlib import Path
import tempfile
import unittest

from v3.host.qualification_runner import (
    FileNamespace, QualificationCampaign,
)
from v3.runtime.iotmd_next.qualification import OperationalQualification


class V3QualificationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.now = [1000]
        self.path = Path(self.temporary.name) / 'state.json'
        self.recorder = OperationalQualification(
            FileNamespace(self.path), lambda: self.now[0], 'iot-md-001',
            lambda: {'version': '3.0.0-alpha.6', 'sequence': 2711,
                     'confirmed': True},
            {
                'name': 'test', 'minimum_soak_s': 60,
                'maximum_consecutive_unhealthy': 1,
                'minimum_health_samples': 1,
                'minimum_storage_samples': 1,
                'minimum_storage_free_bytes': 100,
                'maximum_network_recovery_s': 20,
                'required_network_recoveries': 1,
                'required_renewals': 1,
                'required_update_confirmations': 1,
                'required_power_recoveries': 1,
                'required_native_recoveries': 1,
                'required_watchdog_recoveries': 1,
                'required_identity_transactions': 1,
                'required_fleet_transactions': 1,
                'required_migration_rollbacks': 1,
                'required_driver_checks': 1,
            }
        )
        self.recorder.start()

    def test_file_namespace_persists_generation_and_payload(self):
        self.recorder.sample('healthy', 200, True)
        stored = json.loads(self.path.read_text())
        self.assertGreater(stored['generation'], 0)
        restarted = OperationalQualification(
            FileNamespace(self.path), lambda: self.now[0], 'iot-md-001',
            lambda: {'version': '3.0.0-alpha.6', 'sequence': 2711,
                     'confirmed': True}, self.recorder._profile
        )
        self.assertEqual(restarted.start()['counters']['samples'], 1)

    def test_unreachable_probe_records_network_only(self):
        campaign = QualificationCampaign(self.recorder)
        result = campaign.observe(
            lambda: (_ for _ in ()).throw(OSError('offline'))
        )
        self.assertEqual(result['counters']['health_samples'], 0)
        self.assertIsNone(result['measurements']['minimum_storage_free_bytes'])
        self.assertTrue(result['measurements']['network_outage_open'])

    def test_recovery_is_measured_after_probe_returns(self):
        campaign = QualificationCampaign(self.recorder)
        campaign.observe(lambda: {'health_state': 'healthy',
                                   'storage_free_bytes': 200})
        self.now[0] += 1
        campaign.observe(lambda: (_ for _ in ()).throw(OSError('offline')))
        self.now[0] += 10
        result = campaign.observe(lambda: {
            'health_state': 'healthy', 'storage_free_bytes': 180,
        })
        self.assertEqual(result['counters']['network_recoveries'], 1)
        self.assertEqual(result['measurements']['maximum_network_recovery_s'], 10)


if __name__ == '__main__':
    unittest.main()
