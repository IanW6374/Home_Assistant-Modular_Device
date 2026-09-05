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
from v3.runtime.iotmd_next.resources import ResourceConflict, ResourceManager


ROOT = Path(__file__).resolve().parents[1]


class KernelProvider:
    ABI_VERSION = 5

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

    def resource_claim(self, kind, identifier, owner, shared=False, signature=''):
        for handle, item in self.resources.items():
            if item['kind'] == kind and item['identifier'] == identifier:
                if item['owner'] == owner:
                    return handle
                raise OSError(errno.EBUSY)
        handle = self.next_handle
        self.next_handle += 1
        self.resources[handle] = {
            'handle': handle, 'kind': kind, 'identifier': identifier,
            'owner': owner, 'shared': bool(shared),
            'signature': signature, 'constructed': False,
        }
        return handle

    def resource_construct(self, handle, parameters):
        self.resources[handle]['constructed'] = True
        self.resources[handle]['parameters'] = dict(parameters)
        return {'handle': handle, 'kind': self.resources[handle]['kind'],
                'state': 'shared' if self.resources[handle]['shared'] else 'constructed'}

    def resource_recover(self, handle):
        return handle in self.resources

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

    def resource_reset(self):
        released = len(self.resources)
        self.resources.clear()
        return released

    def resource_snapshot(self):
        return [{key: value for key, value in self.resources[item].items()
                 if key != 'parameters'} for item in sorted(self.resources)]

    def update_snapshot(self):
        return {
            'running_label': 'ota_0', 'running_state': 'valid',
            'next_label': 'ota_1', 'pending_verify': False,
            'can_confirm': False, 'can_rollback': False,
        }

    def update_confirm(self, expected): return True

    def update_rollback(self, expected): return None

    def recovery_boot_begin(self): return 0
    def recovery_snapshot(self):
        return {'requested': False, 'reason': '', 'boot_pending': False,
                'boot_count': 1, 'failed_boots': 0, 'reset_reason': 1}
    def recovery_request(self, reason): return True
    def recovery_mark_healthy(self): return True
    def recovery_clear(self): return True
    def job_submit(self, kind, argument): return 1
    def event_poll(self): return None


def configuration():
    value = json.loads((
        ROOT / 'v3' / 'contracts' / 'examples' /
        'runtime-configuration.json'
    ).read_text())
    value['transports'] = []
    return value


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
        self.assertEqual(plan['configuration']['contract_version'], 4)
        self.assertEqual(plan['configuration']['transports'], [])
        self.assertEqual(
            plan['configuration']['modules'][0]['resources'],
            [{'kind': 'adc', 'identifier': 'adc:1', 'shared': False,
              'signature': '', 'parameters': {}}],
        )

    def test_unknown_or_duplicate_configuration_fails_before_claiming(self):
        value = configuration()
        value['unexpected'] = True
        kernel = ApplicationKernel(self.platform)
        with self.assertRaises(ConfigurationError):
            kernel.boot(value)
        self.assertEqual(kernel.snapshot()['kernel_state'], 'recovery')
        self.assertEqual(self.provider.resources, {})

    def test_only_bus_resources_can_be_shared(self):
        value = configuration()
        resource = value['modules'][0]['resources'][0]
        resource.update({'shared': True, 'signature': 'adc-shared'})
        with self.assertRaisesRegex(ConfigurationError, 'cannot be shared'):
            ApplicationKernel(self.platform).boot(value)

        value = configuration()
        resource = value['modules'][0]['resources'][0]
        resource.update({
            'kind': 'i2c', 'identifier': 'i2c:0', 'shared': True,
            'signature': 'i2c0-sda8-scl9-400k',
            'parameters': {'sda': 8, 'scl': 9, 'frequency': 400000},
        })
        ApplicationKernel(self.platform).boot(value)
        self.assertTrue(next(iter(self.provider.resources.values()))['shared'])

    def test_physical_parameters_are_kind_specific_and_bounded(self):
        value = configuration()
        value['modules'][0]['resources'][0]['parameters']['frequency'] = 400000
        with self.assertRaisesRegex(ConfigurationError, 'unsupported'):
            ApplicationKernel(self.platform).boot(value)

        value = configuration()
        value['modules'][0]['resources'][0]['parameters']['attenuation'] = 99
        with self.assertRaisesRegex(ConfigurationError, 'invalid'):
            ApplicationKernel(self.platform).boot(value)

    def test_idempotent_claim_rejects_changed_sharing_contract(self):
        resources = ResourceManager(self.platform)
        resources.claim('i2c', 'i2c:0', 'module-1', True, 'bus-a')
        with self.assertRaisesRegex(ResourceConflict, 'configuration changed'):
            resources.claim('i2c', 'i2c:0', 'module-1', True, 'bus-b')

    def test_resource_manager_clears_stale_native_claims_on_reconstruction(self):
        self.provider.resources[7] = {
            'handle': 7, 'kind': 'gpio', 'identifier': 'gpio:4',
            'owner': 'stale-module', 'shared': False, 'signature': '',
            'constructed': True,
        }
        ResourceManager(self.platform)
        self.assertEqual(self.provider.resources, {})

    def test_v3_migration_rejects_unknown_fields_before_translation(self):
        value = configuration()
        value['contract_version'] = 3
        for module in value['modules']:
            module['resources'] = [
                {'kind': item['kind'], 'identifier': item['identifier']}
                for item in module['resources']
            ]
        value['modules'][0]['resources'][0]['unsafe'] = True
        with self.assertRaisesRegex(ConfigurationError, 'invalid fields'):
            migrate_configuration(value)

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
        self.assertEqual(support['platform_abi'], 5)
        self.assertNotIn('settings', json.dumps(support).lower())


if __name__ == '__main__':
    unittest.main()
