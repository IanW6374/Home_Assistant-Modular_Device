import unittest

from alpha_qualification import AlphaQualificationService


class Recorder:
    def __init__(self):
        self.started = 0
        self.samples = []
        self.updates = []

    def start(self):
        self.started += 1

    def sample(self, *values):
        self.samples.append(values)
        return self.snapshot()

    def record_update(self, outcome):
        self.updates.append(outcome)

    def snapshot(self):
        return {
            'promotion_ready': False,
            'gates': [
                {'name': 'soak', 'status': 'in-progress'},
                {'name': 'power-recovery', 'status': 'not-run'},
            ],
        }


class AlphaQualificationTests(unittest.TestCase):
    def test_lazy_recorder_reports_and_records_observations(self):
        recorder = Recorder()
        service = AlphaQualificationService(
            'device', lambda: {}, lambda: 1,
            lambda clock, device, release: recorder
        )
        self.assertEqual(service.status()['summary'], 'In progress')
        self.assertEqual(recorder.started, 1)
        service.observe('healthy', 1000, True)
        service.record_update('confirmed')
        self.assertEqual(recorder.samples, [('healthy', 1000, True, False)])
        self.assertEqual(recorder.updates, ['confirmed'])

    def test_unavailable_recorder_is_fail_closed(self):
        service = AlphaQualificationService(
            'device', lambda: {}, lambda: 1,
            lambda *args: (_ for _ in ()).throw(RuntimeError('no platform'))
        )
        status = service.status()
        self.assertFalse(status['available'])
        self.assertEqual(status['summary'], 'Unavailable')
        self.assertIn('no platform', status['error'])

    def test_missing_native_core_has_actionable_error(self):
        service = AlphaQualificationService(
            'device', lambda: {}, lambda: 1,
            lambda *args: (_ for _ in ()).throw(
                RuntimeError('native v3 platform is unavailable')
            )
        )
        status = service.status()
        self.assertIn('install the universal release', status['error'])

    def test_native_update_state_distinguishes_mechanism_and_qualification(self):
        class Platform:
            def capabilities(self):
                return {
                    'updates': {
                        'native_trial_observation': True,
                        'native_trial_control': True,
                        'paired_trial': False,
                        'native_rollback': False,
                    },
                    'recovery': {
                        'product_independent': True, 'qualified': False,
                    },
                    'jobs': {'async_worker': True, 'qualified': False},
                }

            def update_snapshot(self):
                return {
                    'running_label': 'ota_0', 'running_state': 'valid',
                    'next_label': 'ota_1', 'pending_verify': False,
                    'can_confirm': False, 'can_rollback': False,
                }

            def recovery_snapshot(self):
                return {'requested': False, 'failed_boots': 0}

        service = AlphaQualificationService(
            'device', lambda: {}, lambda: 1, lambda *args: Recorder()
        )
        service.platform = Platform()
        native = service.status()['native_update']
        self.assertTrue(native['control_available'])
        self.assertFalse(native['paired_trial_qualified'])
        self.assertTrue(native['recovery_available'])
        self.assertTrue(native['jobs_available'])
        self.assertEqual(native['snapshot']['running_label'], 'ota_0')

    def test_missing_storage_is_not_reported_as_zero_free_bytes(self):
        value = AlphaQualificationService.observation('', False, {}, False)
        self.assertIsNone(value['storage_free_bytes'])


if __name__ == '__main__':
    unittest.main()
