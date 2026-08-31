import json
import os
import tempfile
import unittest
from pathlib import Path

import boot_state


class MemoryPlatform:
    def __init__(self, backup=True, heap=2 * 1024 * 1024):
        self.value = b''
        self.backup = backup
        self.heap = heap

    def backup_memory_read(self):
        return self.value if self.backup else b''

    def backup_memory_write(self, value):
        if not self.backup:
            return False
        self.value = bytes(value)
        return True

    def backup_memory_clear(self):
        self.value = b''
        return self.backup

    def heap_capability(self):
        return {'gc_free_bytes': self.heap}


class BootStateTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def test_backup_record_is_crc_protected(self):
        value = boot_state._empty()
        encoded = boot_state._encode_backup(value)
        self.assertEqual(boot_state._decode_backup(encoded), value)
        damaged = encoded[:-1] + bytes((encoded[-1] ^ 1,))
        with self.assertRaisesRegex(ValueError, 'checksum'):
            boot_state._decode_backup(damaged)

    def test_incomplete_reset_increments_failure_count(self):
        platform = MemoryPlatform()
        first = boot_state.BootStateStore(platform=platform)
        first.begin('power-on')
        first.stage('platform')

        second = boot_state.BootStateStore(platform=platform)
        snapshot = second.begin('watchdog')

        self.assertEqual(snapshot['boot_count'], 2)
        self.assertEqual(snapshot['failure_count'], 1)
        self.assertEqual(snapshot['reset_cause'], 'watchdog')

    def test_significant_transitions_are_mirrored_to_flash(self):
        platform = MemoryPlatform()
        store = boot_state.BootStateStore(platform=platform)
        store.begin('soft-reset')
        store.stage('platform')
        store.confirm_health()

        flash = json.loads(Path(boot_state.STATE_PATH).read_text())
        self.assertTrue(flash['healthy'])
        self.assertFalse(flash['incomplete'])
        self.assertEqual(flash['stage'], 'health-check')

    def test_flash_is_used_when_backup_memory_is_unavailable(self):
        platform = MemoryPlatform(backup=False)
        store = boot_state.BootStateStore(platform=platform)
        store.begin('power-on')
        store.stage('platform')
        store.stage('persistent-state')

        loaded = boot_state.BootStateStore(platform=platform).snapshot()
        self.assertEqual(loaded['stage'], 'persistent-state')

    def test_newer_flash_checkpoint_wins_over_stale_backup_from_same_boot(self):
        platform = MemoryPlatform()
        store = boot_state.BootStateStore(platform=platform)
        store.begin('power-on')
        store.stage('platform')
        stale_backup = platform.value
        store.stage('persistent-state', durable=True)
        platform.value = stale_backup

        loaded = boot_state.BootStateStore(platform=platform).snapshot()

        self.assertEqual(loaded['stage'], 'persistent-state')
        self.assertGreater(loaded['checkpoint_generation'], 1)

    def test_normal_stages_cannot_move_backwards(self):
        store = boot_state.BootStateStore(platform=MemoryPlatform())
        store.begin('power-on')
        store.stage('platform')
        store.stage('certificates')
        with self.assertRaisesRegex(ValueError, 'move backwards'):
            store.stage('configuration')

    def test_failure_is_idempotent_within_one_boot(self):
        store = boot_state.BootStateStore(platform=MemoryPlatform())
        store.begin('power-on')
        store.fail('application failed')
        store.fail('entering safe mode', safe=True)
        self.assertEqual(store.snapshot()['failure_count'], 1)
        self.assertEqual(store.snapshot()['device_state'], 'safe')


if __name__ == '__main__':
    unittest.main()
