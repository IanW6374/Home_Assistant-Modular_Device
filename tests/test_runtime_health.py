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
        health.observe_heap(50000)
        health.observe_heap(60000)
        health.observe_heap(40000)
        health.observe_wifi(-55)
        health.observe_wifi(-72, reconnected=True)

        snapshot = health.snapshot()
        self.assertEqual(snapshot['observations']['minimum_free_heap'], 40000)
        self.assertEqual(snapshot['observations']['minimum_wifi_rssi'], -72)
        self.assertEqual(snapshot['observations']['last_wifi_rssi'], -72)
        self.assertEqual(snapshot['counters']['wifi_reconnects'], 1)

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


if __name__ == '__main__':
    unittest.main()
