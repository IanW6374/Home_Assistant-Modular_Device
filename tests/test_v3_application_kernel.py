import copy
import errno
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from v3.runtime.iotmd_next.configuration import (
    ConfigurationError, migrate_configuration,
)
from v3.runtime.iotmd_next.kernel import ApplicationKernel, EventJournal
from v3.runtime.iotmd_next.platform import Platform
from v3.runtime.iotmd_next.reference_sensor import ReferenceSensor


ROOT = Path(__file__).resolve().parents[1]


class KernelProvider:
    ABI_VERSION = 3

    def __init__(self):
        self.resources = {}
        self.next_handle = 1

    def capabilities(self):
        return json.loads((
            ROOT / 'v3' / 'contracts' / 'examples' /
            'platform-capabilities.json'
        ).read_text())

    def storage_open(self, namespace):
        return 1

    def storage_close(self, handle):
        return None

    def storage_snapshot(self, handle):
        return {'generation': 0, 'payload': b''}

    def storage_commit(self, handle, generation, payload):
        return generation + 1

    def resource_claim(self, kind, identifier, owner):
        for handle, item in self.resources.items():
            if item['kind'] == kind and item['identifier'] == identifier:
                if item['owner'] == owner:
                    return handle
                raise OSError(errno.EBUSY)
        handle = self.next_handle
        self.next_handle += 1
        self.resources[handle] = {
            'handle': handle, 'kind': kind, 'identifier': identifier,
            'owner': owner,
        }
        return handle

    def resource_release(self, handle):
        del self.resources[handle]

    def resource_release_owner(self, owner):
        handles = [
            handle for handle, item in self.resources.items()
            if item['owner'] == owner
        ]
        for handle in handles:
            del self.resources[handle]
        return len(handles)

    def resource_snapshot(self):
        return [dict(self.resources[key]) for key in sorted(self.resources)]


def configuration():
    return json.loads((
        ROOT / 'v3' / 'contracts' / 'examples' /
        'runtime-configuration.json'
    ).read_text())


class V3ApplicationKernelTests(unittest.TestCase):
    def setUp(self):
        self.provider = KernelProvider()
        self.platform = Platform(self.provider)

    def test_v0_migration_is_previewed_without_mutating_source(self):
        source = {
            'version': 0,
            'device_name': 'iot-md-001',
            'modules': [{
                'name': 'reference-1',
                'driver': 'reference-sensor',
                'resource': {'kind': 'adc', 'identifier': 'adc:1'},
                'settings': {'scale': 2},
            }],
        }
        original = copy.deepcopy(source)
        plan = migrate_configuration(source)
        self.assertEqual(source, original)
        self.assertTrue(plan['changed'])
        self.assertEqual(plan['configuration']['contract_version'], 1)

    def test_unknown_or_duplicate_configuration_fails_before_claiming(self):
        value = configuration()
        value['unexpected'] = True
        kernel = ApplicationKernel(self.platform)
        with self.assertRaises(ConfigurationError):
            kernel.boot(value)
        self.assertEqual(kernel.snapshot()['kernel_state'], 'recovery')
        self.assertEqual(self.provider.resources, {})

        value = configuration()
        value['modules'].append(copy.deepcopy(value['modules'][0]))
        with self.assertRaisesRegex(ConfigurationError, 'duplicated'):
            ApplicationKernel(self.platform).boot(value)
        self.assertEqual(self.provider.resources, {})

    def test_reference_module_runs_restarts_and_releases_its_resource(self):
        readings = iter((20, 21, 22))

        def factory(value):
            return ReferenceSensor(
                kernel._resources, value, lambda identifier: next(readings)
            )

        kernel = ApplicationKernel(self.platform, {
            'reference-sensor': factory,
        })
        kernel.boot(configuration())
        kernel.poll()
        snapshot = kernel.snapshot()
        self.assertEqual(snapshot['kernel_state'], 'running')
        self.assertEqual(snapshot['services'][0]['detail']['value'], 20)
        kernel.restart_service('reference-1')
        kernel.poll()
        self.assertEqual(
            kernel.snapshot()['services'][0]['detail']['value'], 21
        )
        kernel.shutdown()
        self.assertEqual(self.provider.resources, {})
        kernel.boot(configuration())
        kernel.poll()
        self.assertEqual(
            kernel.snapshot()['services'][0]['detail']['value'], 22
        )
        kernel.shutdown()

    def test_resource_conflict_enters_recovery_and_cleans_started_module(self):
        value = configuration()
        second = copy.deepcopy(value['modules'][0])
        second['id'] = 'reference-2'
        value['modules'].append(second)
        kernel = ApplicationKernel(self.platform)
        with self.assertRaisesRegex(Exception, 'module start failed'):
            kernel.boot(value)
        self.assertEqual(kernel.snapshot()['kernel_state'], 'recovery')
        self.assertEqual(self.provider.resources, {})

    def test_transient_poll_failure_is_isolated_and_can_recover(self):
        outcomes = iter((RuntimeError('password=must-not-leak'), 12))

        def read(identifier):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def factory(value):
            return ReferenceSensor(kernel._resources, value, read)

        kernel = ApplicationKernel(
            self.platform, {'reference-sensor': factory}
        )
        kernel.boot(configuration())
        kernel.poll()
        degraded = kernel.snapshot()
        self.assertEqual(degraded['services'][0]['state'], 'degraded')
        self.assertNotIn('must-not-leak', json.dumps(degraded))
        kernel.poll()
        self.assertEqual(kernel.snapshot()['services'][0]['state'], 'running')

    def test_event_and_support_snapshots_are_bounded_and_schema_valid(self):
        events = EventJournal()
        for index in range(40):
            events.add('event-' + str(index), 'test', 'info')
        self.assertEqual(len(events.snapshot()), 32)
        self.assertEqual(events.snapshot()[0]['sequence'], 9)

        kernel = ApplicationKernel(self.platform)
        kernel.boot(configuration())
        kernel.poll()
        snapshot = kernel.snapshot()
        self.assertEqual(snapshot['health']['state'], 'healthy')
        schema = json.loads((
            ROOT / 'v3' / 'contracts' / 'kernel-snapshot.schema.json'
        ).read_text())
        Draft202012Validator(schema).validate(snapshot)
        support = kernel.support_snapshot()
        self.assertEqual(support['platform_abi'], 3)
        self.assertNotIn('settings', json.dumps(support).lower())


if __name__ == '__main__':
    unittest.main()
