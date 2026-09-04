import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from v3.runtime.iotmd_next.configuration import (
    ConfigurationError, migrate_configuration, validate_configuration,
)
from v3.runtime.iotmd_next.drivers import (
    SUPPORTED_DRIVER_TYPES, DriverService, driver_catalog,
)
from v3.runtime.iotmd_next.fleet import FleetError, FleetPolicyService
from v3.runtime.iotmd_next.identity import (
    IdentityError, IdentityLifecycleService, validate_identity_state,
)
from v3.runtime.iotmd_next.kernel import ApplicationKernel
from v3.runtime.iotmd_next.migration import (
    MigrationError, V2MigrationCoordinator,
)
from v3.runtime.iotmd_next.product_transports import DeviceAPIService
from v3.runtime.iotmd_next.transport_contracts import TransportRequest


ROOT = Path(__file__).resolve().parents[1]


class MemoryNamespace:
    def __init__(self):
        self.generation = 0
        self.payload = b''

    def snapshot(self):
        return self.generation, self.payload

    def commit(self, generation, payload):
        if generation != self.generation:
            raise RuntimeError('stale generation')
        self.generation += 1
        self.payload = bytes(payload)
        return self.generation


def identity_state(method='automatic-iot-ca', due_at=2000):
    return {
        'contract_version': 1, 'generation': 1, 'method': method,
        'identities': [{
            'purpose': 'portal', 'certificate_handle': 11, 'key_handle': 21,
            'subject': 'iot-md-001.example.net', 'issuer': 'Test CA',
            'fingerprint': 'a' * 64, 'not_before': 1000, 'not_after': 2500,
        }],
        'renewal': {
            'managed': method != 'manual-package',
            'state': 'manual' if method == 'manual-package' else 'current',
            'due_at': 0 if method == 'manual-package' else due_at,
        },
    }


class IdentityAdapter:
    def __init__(self, method='automatic-iot-ca'):
        self.value = identity_state(method)
        self.renewed = 0
        self.trust = [{
            'id': 'mqtt-root', 'purpose': 'mqtt', 'subject': 'MQTT CA',
            'fingerprint': 'b' * 64, 'generation': 2,
        }]

    def start(self):
        return None

    def stop(self):
        return None

    def poll(self):
        return None

    def identity_state(self):
        return copy.deepcopy(self.value)

    def enroll(self, method, authorization):
        self.value = identity_state(method, 4000)
        self.value['generation'] += 1
        return self.identity_state()

    def renew(self):
        self.renewed += 1
        self.value['generation'] += 1
        self.value['renewal']['due_at'] += 2000
        return self.identity_state()

    def trust_inventory(self):
        return copy.deepcopy(self.trust)

    def remove_trust(self, identifier, generation):
        if generation != self.trust[0]['generation']:
            raise RuntimeError('stale trust generation')
        self.trust = [item for item in self.trust if item['id'] != identifier]
        return self.trust_inventory()


def identity_configuration(method='automatic-iot-ca'):
    return {
        'enabled': True, 'method': method, 'critical': True,
        'dependencies': ['wifi'], 'renewal_check_s': 60,
    }


def fleet_policy(sequence=1, target='hardware-1'):
    return {
        'format_version': 1, 'target_board': 'esp32-s3',
        'policy_sequence': sequence, 'issued_at': 1900, 'not_before': 1950,
        'expires_at': 3000, 'target_device': target,
        'target_cohort': '',
        'maintenance': {
            'weekdays': [0, 2], 'start_minute': 60,
            'duration_minutes': 30,
        },
        'updates': {
            'channel': 'alpha', 'automatic_download': True,
            'automatic_activation': False,
            'maximum_consecutive_failures': 2,
        },
        'telemetry': {
            'enabled': True, 'minimum_interval_s': 60,
            'severities': ['warning', 'error'],
        },
        'commands': [{
            'id': 'check-1', 'action': 'check-update',
            'release_sequence': 0,
        }],
        'signature_scheme': 'ecdsa-p256-sha256',
        'signature': 'a' * 128,
    }


def fleet_service(namespace=None, clock=lambda: True):
    return FleetPolicyService(
        namespace or MemoryNamespace(),
        lambda value: value['signature'] == 'a' * 128,
        {
            'enabled': True, 'critical': False, 'dependencies': ['wifi'],
            'cohort': 'alpha-canary', 'poll_interval_s': 60,
        },
        'hardware-1', lambda: {
            'board': 'esp32-s3', 'modules': 2, 'transports': 5,
        }, lambda: {
            'state': 'healthy', 'services_degraded': 0, 'services_failed': 0,
        }, lambda: {
            'version': '3.0.0-alpha.5', 'sequence': 2710,
            'confirmed': True,
        }, lambda: 2000, clock,
    )


class StagingAdapter:
    def __init__(self):
        self.next_handle = 1
        self.staged = []
        self.activated = []
        self.discarded = []

    def stage(self, name, payload):
        handle = self.next_handle
        self.next_handle += 1
        self.staged.append((name, handle, payload))
        return handle

    def activate(self, handles):
        self.activated.extend(handles)

    def discard(self, handles):
        self.discarded.extend(handles)


def v2_backup():
    return {
        'format_version': 2, 'created_at': 1900,
        'metadata': {'device_id': 'old-hardware'},
        'credentials': {'device_name': 'iot-md-001', 'wifi': {'ssid': 'home'}},
        'module_settings': {'devices': [{'uuid': '0001'}]},
        'files': {'mqtt_ca': b'certificate'},
    }


class ResourceManager:
    def __init__(self):
        self.claimed = []

    def claim(self, kind, identifier, owner):
        handle = len(self.claimed) + 1
        self.claimed.append((handle, kind, identifier, owner))
        return handle

    def release_owner(self, owner):
        before = len(self.claimed)
        self.claimed = [item for item in self.claimed if item[3] != owner]
        return before - len(self.claimed)


class DriverBackend:
    def __init__(self):
        self.handles = ()
        self.polls = 0

    def start(self, handles, settings):
        self.handles = handles

    def stop(self):
        self.handles = ()

    def poll(self):
        self.polls += 1

    def snapshot(self):
        return {'state': 'healthy'}


class OrderedService:
    def __init__(self, name, order):
        self.name = name
        self.order = order

    def start(self):
        self.order.append(self.name)

    def stop(self):
        return None

    def poll(self):
        return None

    def snapshot(self):
        return {'state': 'online'}


class NoResourcePlatform:
    provider = None

    def __init__(self):
        self.provider = self

    def capabilities(self):
        return {
            'resources': {
                'managed': True, 'max_claims': 32,
                'kinds': ['adc', 'gpio', 'i2c', 'spi', 'uart'],
            },
        }

    def resource_snapshot(self):
        return []


class APIAdapter:
    def start(self, handler, require_mtls=False):
        self.handler = handler
        self.require_mtls = require_mtls

    def stop(self):
        return None

    def poll(self):
        return None

    def status(self):
        return {'state': 'online'}


class V3IdentityFleetMigrationTests(unittest.TestCase):
    def test_alpha4_configuration_migrates_without_mutation(self):
        current = json.loads((
            ROOT / 'v3/contracts/examples/runtime-configuration.json'
        ).read_text())
        previous = copy.deepcopy(current)
        previous['contract_version'] = 2
        del previous['identity']
        del previous['fleet']
        for module in previous['modules']:
            module['resource'] = module.pop('resources')[0]
        original = copy.deepcopy(previous)
        plan = migrate_configuration(previous)
        self.assertEqual(previous, original)
        self.assertEqual(plan['to_version'], 3)
        self.assertFalse(plan['configuration']['fleet']['enabled'])
        self.assertEqual(len(plan['configuration']['modules'][0]['resources']), 1)

    def test_configuration_accepts_domain_dependencies_and_rejects_collision(self):
        value = json.loads((
            ROOT / 'v3/contracts/examples/runtime-configuration.json'
        ).read_text())
        value['identity']['enabled'] = True
        value['identity']['dependencies'] = ['wifi']
        value['fleet']['enabled'] = True
        value['fleet']['dependencies'] = ['wifi', 'identity']
        validate_configuration(value)
        value['transports'][0]['id'] = 'identity'
        with self.assertRaisesRegex(ConfigurationError, 'duplicated'):
            validate_configuration(value)

    def test_kernel_orders_identity_and_fleet_after_their_dependencies(self):
        value = json.loads((
            ROOT / 'v3/contracts/examples/runtime-configuration.json'
        ).read_text())
        value['transports'] = [value['transports'][0]]
        value['identity'].update({
            'enabled': True, 'dependencies': ['wifi'],
        })
        value['fleet'].update({
            'enabled': True, 'dependencies': ['identity'],
        })
        value['modules'] = []
        order = []
        kernel = ApplicationKernel(
            NoResourcePlatform(),
            service_factories={
                'wifi': lambda unused: OrderedService('wifi', order),
            },
            domain_factories={
                'identity': lambda unused: OrderedService('identity', order),
                'fleet': lambda unused: OrderedService('fleet', order),
            },
        )
        kernel.boot(value)
        self.assertEqual(order, ['wifi', 'identity', 'fleet'])

    def test_managed_identity_renews_and_manual_identity_never_does(self):
        now = [1900]
        adapter = IdentityAdapter()
        service = IdentityLifecycleService(
            adapter, identity_configuration(), lambda: now[0], lambda: True
        )
        service.start()
        service.poll()
        self.assertEqual(adapter.renewed, 0)
        now[0] = 2000
        service.poll()
        self.assertEqual(adapter.renewed, 1)
        self.assertEqual(service.snapshot()['renewals'], 1)

        manual = IdentityAdapter('manual-package')
        manual_service = IdentityLifecycleService(
            manual, identity_configuration('manual-package'),
            lambda: 999999, lambda: True
        )
        manual_service.start()
        manual_service.poll()
        self.assertEqual(manual.renewed, 0)
        self.assertEqual(manual_service.snapshot()['renewal'], 'manual')

    def test_identity_trust_removal_is_generation_guarded(self):
        adapter = IdentityAdapter()
        service = IdentityLifecycleService(
            adapter, identity_configuration(), lambda: 1000, lambda: True
        )
        service.start()
        self.assertEqual(service.remove_trust('mqtt-root', 2), [])
        self.assertEqual(service.snapshot()['trust_anchors'], 0)

    def test_identity_rejects_secret_material_and_invalid_manual_renewal(self):
        value = identity_state('manual-package')
        value['private_key'] = b'secret'
        with self.assertRaises(IdentityError):
            validate_identity_state(value)
        value = identity_state('manual-package')
        value['renewal'] = {'managed': True, 'state': 'current', 'due_at': 1}
        with self.assertRaisesRegex(IdentityError, 'manual'):
            validate_identity_state(value)

    def test_signed_fleet_policy_is_target_time_and_sequence_gated(self):
        service = fleet_service()
        service.start()
        service.apply_policy(fleet_policy())
        self.assertEqual(service.snapshot()['policy_sequence'], 1)
        with self.assertRaisesRegex(FleetError, 'not newer'):
            service.apply_policy(fleet_policy())
        with self.assertRaisesRegex(FleetError, 'target'):
            service.apply_policy(fleet_policy(2, 'different-device'))
        with self.assertRaisesRegex(FleetError, 'clock'):
            other = fleet_service(clock=lambda: False)
            other.start()
            other.apply_policy(fleet_policy())

    def test_canary_failure_threshold_pauses_and_success_clears(self):
        service = fleet_service()
        service.start()
        service.apply_policy(fleet_policy())
        service.record_outcome('failed')
        self.assertFalse(service.snapshot()['rollout_paused'])
        service.record_outcome('rolled-back')
        self.assertTrue(service.snapshot()['rollout_paused'])
        service.record_outcome('confirmed')
        self.assertFalse(service.snapshot()['rollout_paused'])
        report = service.report()
        self.assertEqual(report['release']['sequence'], 2710)

    def test_fleet_api_requires_dedicated_scopes(self):
        fleet = fleet_service()
        fleet.start()
        adapter = APIAdapter()
        api = DeviceAPIService(adapter, lambda: {}, lambda: {}, fleet=fleet)
        api.start()
        denied = adapter.handler(TransportRequest(
            'GET', '/api/v3/fleet/report',
            identity={'verified': True, 'scopes': ['read']}
        ))
        self.assertEqual(denied.status, 403)
        accepted = adapter.handler(TransportRequest(
            'GET', '/api/v3/fleet/report',
            identity={'verified': True, 'scopes': ['fleet:read']}
        ))
        self.assertEqual(accepted.status, 200)

        applied = adapter.handler(TransportRequest(
            'POST', '/api/v3/fleet/policy',
            body=json.dumps(fleet_policy()).encode(),
            identity={'verified': True, 'scopes': ['fleet:write']}
        ))
        self.assertEqual(applied.status, 200)
        self.assertEqual(json.loads(applied.body)['policy_sequence'], 1)

    def test_fleet_report_bounds_untrusted_projection_counts(self):
        service = FleetPolicyService(
            MemoryNamespace(), lambda value: True,
            {
                'enabled': True, 'critical': False, 'dependencies': [],
                'cohort': 'default', 'poll_interval_s': 60,
            },
            'hardware-1', lambda: {
                'board': 'esp32-s3', 'modules': -3, 'transports': 99,
            }, lambda: {
                'state': 'healthy', 'services_degraded': -1,
                'services_failed': 99,
            }, lambda: {
                'version': 'test', 'sequence': -4, 'confirmed': False,
            }, lambda: 2000, lambda: True,
        )
        service.start()
        report = service.report()
        self.assertEqual(report['inventory']['modules'], 0)
        self.assertEqual(report['inventory']['transports'], 8)
        self.assertEqual(report['release']['sequence'], 0)
        self.assertEqual(report['health']['services_degraded'], 0)
        self.assertEqual(report['health']['services_failed'], 20)

    def test_v2_migration_preview_never_contains_secrets(self):
        backup = v2_backup()
        backup['credentials']['wifi_password'] = 'must-not-leak'
        coordinator = V2MigrationCoordinator(
            MemoryNamespace(), StagingAdapter(), lambda: 'migration-1'
        )
        preview = coordinator.preview(backup, 'c' * 64)
        encoded = json.dumps(preview)
        self.assertNotIn('must-not-leak', encoded)
        self.assertEqual(preview['phase'], 'preview')
        self.assertEqual(preview['sections'][1]['count'], 1)

    def test_v2_migration_stages_opaque_handles_and_can_roll_back(self):
        adapter = StagingAdapter()
        coordinator = V2MigrationCoordinator(
            MemoryNamespace(), adapter, lambda: 'migration-1'
        )
        backup = v2_backup()
        coordinator.preview(backup, 'c' * 64)
        staged = coordinator.stage('migration-1', backup, 'c' * 64)
        self.assertEqual(staged['phase'], 'staged')
        self.assertNotIn('device_name', json.dumps(staged['sections'][0]))
        coordinator.begin_trial('migration-1')
        rolled_back = coordinator.finish_trial(
            'migration-1', False, 'health gate failed'
        )
        self.assertEqual(rolled_back['phase'], 'rolled-back')
        self.assertEqual(adapter.discarded, [1, 2, 3])

    def test_v2_migration_confirms_only_after_a_healthy_trial(self):
        adapter = StagingAdapter()
        coordinator = V2MigrationCoordinator(
            MemoryNamespace(), adapter, lambda: 'migration-1'
        )
        backup = v2_backup()
        coordinator.preview(backup, 'c' * 64)
        coordinator.stage('migration-1', backup, 'c' * 64)
        coordinator.begin_trial('migration-1')
        confirmed = coordinator.finish_trial('migration-1', True)
        self.assertEqual(confirmed['phase'], 'confirmed')
        self.assertEqual(adapter.activated, [1, 2, 3])

    def test_v2_migration_requires_matching_authenticated_fingerprint(self):
        coordinator = V2MigrationCoordinator(
            MemoryNamespace(), StagingAdapter(), lambda: 'migration-1'
        )
        backup = v2_backup()
        coordinator.preview(backup, 'c' * 64)
        with self.assertRaisesRegex(MigrationError, 'does not match'):
            coordinator.stage('migration-1', backup, 'd' * 64)

    def test_supported_driver_catalog_matches_v2_index(self):
        expected = {
            'dht11', 'ems', 'grove_ac_voltage', 'hcsr04', 'light',
            'max31865_pt1000', 'modbus_transport', 'rs485_modbus',
            'switch_dimmer', 'switch_onoff', 'whes',
        }
        self.assertEqual(set(SUPPORTED_DRIVER_TYPES), expected)
        self.assertEqual({item['driver'] for item in driver_catalog()}, expected)

    def test_driver_service_claims_multiple_resources_and_releases_them(self):
        resources = ResourceManager()
        backend = DriverBackend()
        service = DriverService(resources, {
            'id': 'modbus-1', 'driver': 'modbus_transport', 'enabled': True,
            'resources': [
                {'kind': 'uart', 'identifier': 'uart:1'},
                {'kind': 'gpio', 'identifier': 'gpio:4'},
            ],
            'settings': {},
        }, backend)
        service.start()
        service.poll()
        self.assertEqual(service.snapshot()['resources'], 2)
        service.stop()
        self.assertEqual(resources.claimed, [])

    def test_alpha5_contract_examples_validate(self):
        pairs = (
            ('identity-state.json', 'identity-state.schema.json'),
            ('fleet-report.json', 'fleet-report.schema.json'),
            ('migration-plan.json', 'migration-plan.schema.json'),
            ('driver-catalog.json', 'driver-catalog.schema.json'),
        )
        for example_name, schema_name in pairs:
            instance = json.loads((
                ROOT / 'v3/contracts/examples' / example_name
            ).read_text())
            schema = json.loads((ROOT / 'v3/contracts' / schema_name).read_text())
            Draft202012Validator(schema).validate(instance)


if __name__ == '__main__':
    unittest.main()
