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

    def test_missing_storage_is_not_reported_as_zero_free_bytes(self):
        value = AlphaQualificationService.observation('', False, {}, False)
        self.assertIsNone(value['storage_free_bytes'])


if __name__ == '__main__':
    unittest.main()
