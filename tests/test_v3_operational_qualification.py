import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from v3.runtime.iotmd_next.qualification import (
    OperationalQualification, QualificationError,
)


ROOT = Path(__file__).resolve().parents[1]


class MemoryNamespace:
    def __init__(self):
        self.generation = 0
        self.payload = b''

    def snapshot(self):
        return self.generation, self.payload

    def commit(self, generation, payload):
        if generation != self.generation:
            raise RuntimeError('generation changed')
        self.generation += 1
        self.payload = bytes(payload)
        return self.generation


def profile(**changes):
    value = {
        'name': 'test',
        'minimum_soak_s': 60,
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
    value.update(changes)
    return value


class V3OperationalQualificationTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000]
        self.namespace = MemoryNamespace()
        self.release = {
            'version': '3.0.0-alpha.6', 'sequence': 2711,
            'confirmed': True,
        }
        self.recorder = OperationalQualification(
            self.namespace, lambda: self.now[0], 'iot-md-001',
            lambda: self.release, profile()
        )
        self.recorder.start()

    def test_untested_gates_are_not_reported_as_passed(self):
        result = self.recorder.snapshot()
        states = {item['name']: item['status'] for item in result['gates']}
        self.assertEqual(states['soak'], 'in-progress')
        self.assertEqual(states['storage'], 'not-run')
        self.assertEqual(states['network-recovery'], 'not-run')
        self.assertEqual(states['certificate-renewal'], 'not-run')
        self.assertEqual(states['release-confirmation'], 'passed')
        self.assertFalse(result['promotion_ready'])

    def test_unconfirmed_release_cannot_be_promoted(self):
        self.release['confirmed'] = False
        result = self.recorder.snapshot()
        states = {item['name']: item['status'] for item in result['gates']}
        self.assertEqual(states['release-confirmation'], 'in-progress')
        self.assertFalse(result['promotion_ready'])

    def test_one_late_sample_does_not_qualify_the_soak(self):
        recorder = OperationalQualification(
            self.namespace, lambda: self.now[0], 'iot-md-001',
            lambda: self.release,
            profile(minimum_health_samples=2, minimum_storage_samples=2)
        )
        recorder.reset()
        self.now[0] = 1060
        result = recorder.sample('healthy', 200, True)
        states = {item['name']: item['status'] for item in result['gates']}
        self.assertEqual(states['soak'], 'passed')
        self.assertEqual(states['health'], 'in-progress')
        self.assertEqual(states['storage'], 'in-progress')
        self.assertFalse(result['promotion_ready'])

    def test_complete_observed_campaign_unlocks_promotion(self):
        self.recorder.sample('healthy', 200, True, False)
        self.now[0] += 2
        self.recorder.sample('healthy', 190, False, False)
        self.now[0] += 10
        self.recorder.sample('healthy', 180, True, False)
        self.recorder.record_renewal(True)
        self.recorder.record_update('confirmed')
        self.recorder.record_power_recovery(True)
        for name in (
            'native-recovery', 'watchdog-recovery',
            'identity-interoperability', 'fleet-interoperability',
            'migration-rollback', 'driver-hardware',
        ):
            self.recorder.record_validation(name, True)
        self.now[0] = 1060
        result = self.recorder.sample('healthy', 170, True, False)
        self.assertTrue(result['promotion_ready'])
        self.assertTrue(all(
            item['status'] == 'passed' for item in result['gates']
        ))
        schema = json.loads((
            ROOT / 'v3/contracts/qualification-evidence.schema.json'
        ).read_text())
        Draft202012Validator(schema).validate(result)

    def test_failures_are_sticky_until_explicit_reset(self):
        self.recorder.sample('degraded', 200, True)
        self.now[0] += 1
        result = self.recorder.sample('failed', 50, True, True)
        states = {item['name']: item['status'] for item in result['gates']}
        self.assertEqual(states['health'], 'failed')
        self.assertEqual(states['storage'], 'failed')
        self.assertEqual(states['canary-health'], 'failed')
        self.recorder.record_renewal(False)
        self.recorder.record_update('rolled-back')
        self.recorder.record_power_recovery(False)
        self.recorder.record_validation('driver-hardware', False)
        states = {
            item['name']: item['status']
            for item in self.recorder.snapshot()['gates']
        }
        self.assertEqual(states['certificate-renewal'], 'failed')
        self.assertEqual(states['paired-updates'], 'failed')
        self.assertEqual(states['power-recovery'], 'failed')
        self.assertEqual(states['driver-hardware'], 'failed')
        reset = self.recorder.reset()
        self.assertEqual(reset['counters']['samples'], 0)

    def test_network_recovery_time_and_open_outage_are_measured(self):
        self.recorder.sample('healthy', 200, True)
        self.now[0] += 1
        self.recorder.sample('healthy', 200, False)
        self.now[0] += 21
        open_outage = self.recorder.snapshot()
        self.assertTrue(open_outage['measurements']['network_outage_open'])
        self.assertEqual(
            next(item for item in open_outage['gates']
                 if item['name'] == 'network-recovery')['status'], 'failed'
        )
        recovered = self.recorder.sample('healthy', 200, True)
        self.assertEqual(recovered['counters']['network_recoveries'], 1)
        self.assertEqual(
            recovered['measurements']['maximum_network_recovery_s'], 21
        )

    def test_state_survives_restart_and_rejects_backward_time(self):
        self.recorder.sample('healthy', 200, True)
        restarted = OperationalQualification(
            self.namespace, lambda: self.now[0], 'iot-md-001',
            lambda: self.release, profile()
        )
        self.assertEqual(restarted.start()['counters']['samples'], 1)
        self.now[0] = 999
        with self.assertRaisesRegex(QualificationError, 'backwards'):
            restarted.sample('healthy', 200, True)

    def test_new_release_starts_a_fresh_evidence_campaign(self):
        self.recorder.sample('healthy', 200, True)
        self.release['version'] = '3.0.0-alpha.7'
        self.release['sequence'] = 2712
        restarted = OperationalQualification(
            self.namespace, lambda: self.now[0], 'iot-md-001',
            lambda: self.release, profile()
        )
        result = restarted.start()
        self.assertEqual(result['release']['version'], '3.0.0-alpha.7')
        self.assertEqual(result['counters']['samples'], 0)


if __name__ == '__main__':
    unittest.main()
