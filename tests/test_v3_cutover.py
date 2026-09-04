import unittest

from v3.runtime.iotmd_next.cutover import CutoverCoordinator, CutoverError


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


class Platform:
    def __init__(self, ready=False):
        self.ready = ready

    def capabilities(self):
        return {'updates': {
            'paired_trial': self.ready, 'native_rollback': self.ready,
        }}


class Compatibility:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.polled = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def poll(self):
        self.polled += 1

    def snapshot(self):
        return {'state': 'running' if self.started > self.stopped else 'stopped'}


class Recovery:
    def __init__(self):
        self.reasons = []

    def request(self, reason):
        self.reasons.append(reason)


class Qualification:
    def __init__(self, ready=False):
        self.ready = ready

    def snapshot(self):
        return {
            'promotion_ready': self.ready,
            'gates': [{
                'name': 'soak',
                'status': 'passed' if self.ready else 'not-run',
            }],
        }


class Kernel:
    def __init__(self, fail_boot=False, fail_health=False):
        self.fail_boot = fail_boot
        self.fail_health = fail_health
        self.started = False
        self.stopped = False

    def boot(self, unused):
        if self.fail_boot:
            raise RuntimeError('boot failed')
        self.started = True

    def poll(self):
        pass

    def shutdown(self):
        self.stopped = True

    def snapshot(self):
        return {
            'health': {'state': 'failed' if self.fail_health else 'healthy'}
        }


class V3CutoverTests(unittest.TestCase):
    def make(self, platform=False, qualified=False, kernel=None, namespace=None):
        self.compatibility = Compatibility()
        self.recovery = Recovery()
        self.kernel = kernel or Kernel()
        return CutoverCoordinator(
            namespace or MemoryNamespace(), Platform(platform),
            lambda: self.kernel, self.compatibility, self.recovery,
            Qualification(qualified)
        )

    def test_compatibility_is_the_persistent_fail_safe_default(self):
        namespace = MemoryNamespace()
        coordinator = self.make(namespace=namespace)
        result = coordinator.boot({})
        self.assertEqual(result['effective_mode'], 'compatibility')
        self.assertEqual(self.compatibility.started, 1)
        restarted = self.make(namespace=namespace)
        self.assertEqual(restarted.snapshot()['requested_mode'], 'compatibility')

    def test_active_mode_is_blocked_without_native_and_observed_gates(self):
        coordinator = self.make()
        with self.assertRaisesRegex(CutoverError, 'native paired trial'):
            coordinator.request_mode('active')
        coordinator = self.make(platform=True)
        with self.assertRaisesRegex(CutoverError, 'qualification soak'):
            coordinator.request_mode('active')

    def test_shadow_starts_compatibility_and_v3_kernel(self):
        coordinator = self.make()
        coordinator.request_mode('shadow')
        result = coordinator.boot({})
        self.assertEqual(result['effective_mode'], 'shadow')
        self.assertEqual(self.compatibility.started, 1)
        self.assertTrue(self.kernel.started)

    def test_active_starts_only_v3_after_all_gates_pass(self):
        coordinator = self.make(platform=True, qualified=True)
        coordinator.request_mode('active')
        result = coordinator.boot({})
        self.assertEqual(result['effective_mode'], 'active')
        self.assertEqual(self.compatibility.started, 0)
        self.assertTrue(self.kernel.started)

    def test_boot_failure_requests_recovery_and_restarts_compatibility(self):
        coordinator = self.make(
            platform=True, qualified=True, kernel=Kernel(fail_boot=True)
        )
        coordinator.request_mode('active')
        with self.assertRaisesRegex(RuntimeError, 'boot failed'):
            coordinator.boot({})
        state = coordinator.snapshot()
        self.assertEqual(state['phase'], 'fallback')
        self.assertEqual(state['requested_mode'], 'compatibility')
        self.assertEqual(state['effective_mode'], 'compatibility')
        self.assertEqual(self.compatibility.started, 1)
        self.assertEqual(self.recovery.reasons, ['boot failed'])

    def test_failed_runtime_health_falls_back(self):
        coordinator = self.make(kernel=Kernel(fail_health=True))
        coordinator.request_mode('shadow')
        coordinator.boot({})
        with self.assertRaisesRegex(CutoverError, 'health gate failed'):
            coordinator.poll()
        self.assertEqual(coordinator.snapshot()['phase'], 'fallback')


if __name__ == '__main__':
    unittest.main()
