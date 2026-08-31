import tempfile
import unittest
from pathlib import Path

from runtime_health import HealthHistory


class RuntimeHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'health.json')

    def tearDown(self):
        self.temp.cleanup()

    def test_persists_boot_counters_and_events(self):
        health = HealthHistory(self.path, checkpoint_changes=100)
        health.record_boot('watchdog reset')

        restored = HealthHistory(self.path)
        snapshot = restored.snapshot()
        self.assertEqual(snapshot['counters']['boots'], 1)
        self.assertEqual(snapshot['counters']['watchdog_resets'], 1)
        self.assertEqual(snapshot['events'][-1]['kind'], 'boot')

    def test_tracks_minimum_heap_and_wifi_rssi(self):
        health = HealthHistory(self.path)
        health.observe_heap(50000, 12000)
        health.observe_heap(60000, 13000)
        health.observe_heap(40000, 14000)
        health.observe_wifi(-55)
        health.observe_wifi(-72, reconnected=True)

        snapshot = health.snapshot()
        self.assertEqual(snapshot['observations']['current_free_heap'], 40000)
        self.assertEqual(snapshot['observations']['current_allocated_heap'], 14000)
        self.assertEqual(snapshot['observations']['minimum_free_heap'], 40000)
        self.assertEqual(snapshot['observations']['minimum_wifi_rssi'], -72)
        self.assertEqual(snapshot['observations']['last_wifi_rssi'], -72)
        self.assertEqual(snapshot['counters']['wifi_reconnects'], 1)

        health.checkpoint(force=True)
        restored = HealthHistory(self.path).snapshot()
        self.assertIsNone(restored['observations']['current_free_heap'])
        self.assertIsNone(restored['observations']['current_allocated_heap'])
        self.assertEqual(restored['observations']['minimum_free_heap'], 40000)

    def test_update_result_is_forced_to_storage(self):
        health = HealthHistory(self.path, checkpoint_changes=100)
        health.record_update_result('firmware', 'confirmed', '2.0.0')

        restored = HealthHistory(self.path).snapshot()
        self.assertEqual(
            restored['observations']['last_update_result']['version'], '2.0.0'
        )

    def test_manual_reset_clears_and_persists_all_history(self):
        health = HealthHistory(self.path)
        health.record_boot('power on')
        health.increment('api_requests', force=True)

        health.clear()

        restored = HealthHistory(self.path).snapshot()
        self.assertEqual(restored['counters']['boots'], 0)
        self.assertEqual(restored['counters']['api_requests'], 0)
        self.assertEqual(restored['events'], [])

    def test_structured_events_have_cursor_severity_and_component(self):
        health = HealthHistory(self.path, max_events=2, checkpoint_changes=100)
        first = health.record_event(
            'network_up', 'connected', severity='info', component='network',
            correlation_id='trial-1'
        )
        health.record_event('mqtt_up', component='mqtt')
        health.record_event('update_ready', component='update')
        health.record_event('network_stable', component='network')

        page = health.events_since(first['id'], 1)
        self.assertEqual(page['event_api_version'], 2)
        self.assertTrue(page['cursor_gap'])
        self.assertEqual(len(page['events']), 1)
        self.assertEqual(page['events'][0]['component'], 'update')
        self.assertEqual(page['events'][0]['severity'], 'info')

    def test_invalid_event_severity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'severity'):
            HealthHistory(self.path).record_event('bad', severity='urgent')


if __name__ == '__main__':
    unittest.main()
