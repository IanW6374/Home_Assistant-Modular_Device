import errno
import json
from pathlib import Path
import unittest

from v3.runtime.iotmd_next.paired_update import (
    PairedUpdateCoordinator, PairedUpdateError, validate_state,
)
from v3.runtime.iotmd_next.platform import Platform
from v3.runtime.iotmd_next.storage import (
    StorageConflict, TransactionalNamespace,
)


ROOT = Path(__file__).resolve().parents[1]


class MemoryProvider:
    ABI_VERSION = 2

    def __init__(self):
        self.namespaces = {}
        self.handles = {}
        self.next_handle = 1
        self.interrupt = ''

    def capabilities(self):
        return json.loads((
            ROOT / 'v3' / 'contracts' / 'examples' /
            'platform-capabilities.json'
        ).read_text())

    def storage_open(self, namespace):
        handle = self.next_handle
        self.next_handle += 1
        self.handles[handle] = namespace
        self.namespaces.setdefault(namespace, (0, b''))
        return handle

    def storage_close(self, handle):
        del self.handles[handle]

    def storage_snapshot(self, handle):
        generation, payload = self.namespaces[self.handles[handle]]
        return {'generation': generation, 'payload': payload}

    def storage_commit(self, handle, expected, payload):
        namespace = self.handles[handle]
        generation, _ = self.namespaces[namespace]
        if generation != expected:
            raise OSError(errno.EAGAIN)
        if self.interrupt == 'before':
            self.interrupt = ''
            raise OSError(errno.EIO)
        self.namespaces[namespace] = (generation + 1, bytes(payload))
        if self.interrupt == 'after':
            self.interrupt = ''
            raise OSError(errno.EIO)
        return generation + 1


def pair(sequence=2707, suffix='a'):
    return {
        'id': 'pair-' + str(sequence),
        'sequence': sequence,
        'platform': {'version': '3.0.0-alpha.2', 'sha256': suffix * 64},
        'runtime': {'version': '3.0.0-alpha.2', 'sha256': 'b' * 64},
    }


class V3TransactionalStorageTests(unittest.TestCase):
    def setUp(self):
        self.provider = MemoryProvider()
        self.namespace = TransactionalNamespace(
            Platform(self.provider), 'paired_update'
        )
        self.coordinator = PairedUpdateCoordinator(self.namespace)

    def test_namespace_uses_generation_compare_and_swap(self):
        generation, payload = self.namespace.snapshot()
        self.assertEqual((generation, payload), (0, b''))
        self.assertEqual(self.namespace.commit(generation, b'first'), 1)
        with self.assertRaises(StorageConflict):
            self.namespace.commit(generation, b'stale')

    def test_pair_cannot_trial_until_both_components_are_staged(self):
        self.coordinator.prepare(pair())
        self.coordinator.mark_staged('platform')
        with self.assertRaisesRegex(PairedUpdateError, 'not ready'):
            self.coordinator.begin_trial()
        _, state = self.coordinator.mark_staged('runtime')
        self.assertEqual(state['phase'], 'ready')
        _, state = self.coordinator.begin_trial()
        self.assertEqual(state['phase'], 'trial')

    def test_mismatched_running_pair_enters_rollback(self):
        self.coordinator.prepare(pair())
        self.coordinator.mark_staged('platform')
        self.coordinator.mark_staged('runtime')
        self.coordinator.begin_trial()
        _, state = self.coordinator.reconcile_trial('c' * 64, 'b' * 64)
        self.assertEqual(state['phase'], 'rollback')
        self.assertIn('does not match', state['failure_reason'])

    def test_confirmed_pair_enforces_monotonic_sequence(self):
        self.coordinator.prepare(pair())
        self.coordinator.mark_staged('platform')
        self.coordinator.mark_staged('runtime')
        self.coordinator.begin_trial()
        self.coordinator.confirm('pair-2707')
        with self.assertRaisesRegex(PairedUpdateError, 'not newer'):
            self.coordinator.prepare(pair())

    def test_each_atomic_interruption_leaves_old_or_new_valid_state(self):
        transitions = [
            lambda c: c.prepare(pair()),
            lambda c: c.mark_staged('platform'),
            lambda c: c.mark_staged('runtime'),
            lambda c: c.begin_trial(),
            lambda c: c.confirm('pair-2707'),
        ]
        for transition_index in range(len(transitions)):
            for point in ('before', 'after'):
                provider = MemoryProvider()
                namespace = TransactionalNamespace(Platform(provider), 'pair')
                coordinator = PairedUpdateCoordinator(namespace)
                for prior in transitions[:transition_index]:
                    prior(coordinator)
                _, old_state = coordinator.state()
                provider.interrupt = point
                try:
                    transitions[transition_index](coordinator)
                except OSError:
                    pass
                _, recovered = coordinator.state()
                validate_state(recovered)
                if point == 'before':
                    self.assertEqual(recovered, old_state)
                else:
                    self.assertNotEqual(recovered, old_state)

    def test_corrupt_or_unknown_persistent_state_fails_closed(self):
        self.provider.namespaces['paired_update'] = (1, b'{"phase":"trial"}')
        with self.assertRaises(PairedUpdateError):
            self.coordinator.state()

    def test_rollback_restores_previous_confirmed_pair(self):
        self.coordinator.prepare(pair())
        self.coordinator.mark_staged('platform')
        self.coordinator.mark_staged('runtime')
        self.coordinator.begin_trial()
        self.coordinator.confirm('pair-2707')
        self.coordinator.prepare(pair(2708, 'c'))
        self.coordinator.request_rollback('test interruption')
        _, state = self.coordinator.complete_rollback()
        self.assertEqual(state['phase'], 'confirmed')
        self.assertEqual(state['pair']['sequence'], 2707)


if __name__ == '__main__':
    unittest.main()
