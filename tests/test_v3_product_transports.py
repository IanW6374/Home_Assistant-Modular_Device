import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from v3.runtime.iotmd_next.configuration import (
    ConfigurationError, migrate_configuration, validate_configuration,
)
from v3.runtime.iotmd_next.connectivity import (
    ConnectivityDiagnostics, PROBE_NAMES,
)
from v3.runtime.iotmd_next.kernel import ApplicationKernel
from v3.runtime.iotmd_next.presentation import form_metadata, navigation
from v3.runtime.iotmd_next.product_transports import (
    DeviceAPIService, MQTTService, PortalService, build_service_factories,
)
from v3.runtime.iotmd_next.transport_contracts import TransportRequest
from v3.runtime.iotmd_next.platform import Platform


ROOT = Path(__file__).resolve().parents[1]


class KernelProvider:
    ABI_VERSION = 4

    def capabilities(self):
        return json.loads((
            ROOT / 'v3/contracts/examples/platform-capabilities.json'
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
        return 1

    def resource_release(self, handle):
        return None

    def resource_release_owner(self, owner):
        return 0

    def resource_snapshot(self):
        return []

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


class Adapter:
    def __init__(self):
        self.started = False
        self.handler = None
        self.mtls = False
        self.published = []

    def start(self, handler=None, require_mtls=False):
        self.started = True
        self.handler = handler
        self.mtls = require_mtls

    def connect(self):
        self.started = True

    def stop(self):
        self.started = False

    def disconnect(self):
        self.started = False

    def poll(self):
        return None

    def publish(self, topic, payload, retain, qos):
        self.published.append((topic, payload, retain, qos))

    def status(self):
        return {'state': 'online' if self.started else 'offline'}


class Service:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    def start(self):
        self.calls.append('start:' + self.name)

    def stop(self):
        self.calls.append('stop:' + self.name)

    def poll(self):
        self.calls.append('poll:' + self.name)

    def snapshot(self):
        return {'state': 'ready'}


def configuration():
    return json.loads((
        ROOT / 'v3/contracts/examples/runtime-configuration.json'
    ).read_text())


class V3ProductTransportTests(unittest.TestCase):
    def test_alpha3_configuration_migrates_without_mutating_source(self):
        current = configuration()
        previous = copy.deepcopy(current)
        previous['contract_version'] = 1
        del previous['transports']
        del previous['identity']
        del previous['fleet']
        for module in previous['modules']:
            module['resource'] = module.pop('resources')[0]
        original = copy.deepcopy(previous)
        plan = migrate_configuration(previous)
        self.assertEqual(previous, original)
        self.assertEqual(plan['from_version'], 1)
        self.assertEqual(plan['to_version'], 3)
        self.assertEqual(plan['configuration']['transports'], [])
        self.assertFalse(plan['configuration']['identity']['enabled'])
        self.assertFalse(plan['configuration']['fleet']['enabled'])

    def test_transport_dependencies_start_before_product_services(self):
        value = configuration()
        value['modules'] = []
        value['transports'] = [
            {
                'id': 'wifi', 'adapter': 'wifi', 'enabled': True,
                'critical': True, 'dependencies': [], 'settings': {},
            },
            {
                'id': 'mqtt', 'adapter': 'mqtt', 'enabled': True,
                'critical': False, 'dependencies': ['wifi'], 'settings': {},
            },
        ]
        calls = []
        factories = {
            'wifi': lambda item: Service(item['id'], calls),
            'mqtt': lambda item: Service(item['id'], calls),
        }
        kernel = ApplicationKernel(
            Platform(KernelProvider()), service_factories=factories
        )
        kernel.boot(value)
        self.assertEqual(calls[:2], ['start:wifi', 'start:mqtt'])
        self.assertEqual(
            [item['name'] for item in kernel.snapshot()['services']],
            ['mqtt', 'wifi'],
        )

    def test_configuration_rejects_unknown_or_duplicate_dependencies(self):
        value = configuration()
        value['transports'] = [{
            'id': 'mqtt', 'adapter': 'mqtt', 'enabled': True,
            'critical': False, 'dependencies': ['wifi'], 'settings': {},
        }]
        with self.assertRaisesRegex(ConfigurationError, 'dependency'):
            validate_configuration(value)
        value = configuration()
        value['transports'] = [{
            'id': 'reference-1', 'adapter': 'wifi', 'enabled': True,
            'critical': True, 'dependencies': [], 'settings': {},
        }]
        with self.assertRaisesRegex(ConfigurationError, 'duplicated'):
            validate_configuration(value)

    def test_connectivity_probes_are_bounded_and_redact_error_messages(self):
        probes = {name: (lambda: True) for name in PROBE_NAMES}

        def tls_failure():
            raise RuntimeError('password=must-not-leak')

        probes['tls'] = tls_failure
        diagnostics = ConnectivityDiagnostics(probes)
        diagnostics.start()
        for unused in PROBE_NAMES:
            diagnostics.poll()
        result = diagnostics.diagnostics()
        self.assertEqual(result['probes']['dns']['state'], 'reachable')
        self.assertEqual(result['probes']['tls']['state'], 'error')
        self.assertEqual(result['probes']['tls']['error'], 'RuntimeError')
        self.assertNotIn('must-not-leak', json.dumps(result))
        schema = json.loads((
            ROOT / 'v3/contracts/connectivity-diagnostics.schema.json'
        ).read_text())
        Draft202012Validator(schema).validate(result)

    def test_mqtt_adapter_publishes_bounded_state_and_discovery(self):
        adapter = Adapter()
        service = MQTTService(
            adapter, lambda: {'health': 'healthy'}, 'iot-md/iot-md-001'
        )
        service.start()
        service.publish_state()
        service.publish_discovery('temperature', {'name': 'Temperature'})
        self.assertEqual(adapter.published[0][0], 'iot-md/iot-md-001/availability')
        self.assertEqual(adapter.published[1][0], 'iot-md/iot-md-001/state')
        self.assertEqual(adapter.published[2][0], 'homeassistant/sensor/temperature/config')
        self.assertEqual(service.snapshot()['published'], 2)

    def test_portal_is_role_aware_server_rendered_and_escapes_values(self):
        adapter = Adapter()
        service = PortalService(
            adapter,
            lambda: {
                'kernel_state': '<running>', 'health': {'state': 'healthy'},
            },
            lambda: {'probes': {'dns': {'state': 'reachable'}}},
        )
        service.start()
        response = adapter.handler(TransportRequest(
            'GET', '/status', identity={'role': 'viewer'}
        ))
        self.assertEqual(response.status, 200)
        self.assertIn('&lt;running&gt;', response.body)
        self.assertNotIn('<running>', response.body)
        self.assertNotIn('/maintenance/upgrades', response.body)
        denied = adapter.handler(TransportRequest('GET', '/status'))
        self.assertEqual(denied.status, 401)

    def test_qualification_is_surfaced_in_overview_detail_and_api(self):
        qualification = type('Qualification', (), {
            'snapshot': lambda unused: {
                'promotion_ready': False,
                'gates': [
                    {'name': 'soak', 'status': 'in-progress',
                     'observed': 30, 'required': 60},
                    {'name': 'storage', 'status': 'passed',
                     'observed': 200, 'required': 100},
                ],
            }
        })()
        portal = PortalService(
            Adapter(),
            lambda: {'kernel_state': 'running',
                     'health': {'state': 'healthy'}},
            lambda: {'probes': {}},
            qualification_getter=qualification.snapshot,
        )
        overview = portal.handle(TransportRequest(
            'GET', '/status', identity={'role': 'viewer'}
        ))
        self.assertIn('Release qualification', overview.body)
        self.assertIn('In progress', overview.body)
        details = portal.handle(TransportRequest(
            'GET', '/maintenance/qualification', identity={'role': 'viewer'}
        ))
        self.assertEqual(details.status, 200)
        self.assertIn('soak', details.body)
        self.assertIn('30 / 60', details.body)

        adapter = Adapter()
        api = DeviceAPIService(
            adapter, lambda: {}, lambda: {}, qualification=qualification
        )
        response = api.handle(TransportRequest(
            'GET', '/api/v3/qualification',
            identity={'verified': True, 'scopes': ['read']}
        ))
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body)
        self.assertEqual(
            payload['qualification']['gates'][0]['name'], 'soak'
        )

    def test_portal_diagnostic_form_uses_metadata_and_operator_role(self):
        adapter = Adapter()
        calls = []
        service = PortalService(
            adapter, lambda: {}, lambda: {'probes': {}},
            lambda target: calls.append(target) or {'state': 'reachable'},
        )
        service.start()
        page = adapter.handler(TransportRequest(
            'GET', '/maintenance/diagnostics',
            identity={'role': 'operator'}
        ))
        self.assertIn('name="target"', page.body)
        self.assertIn('<option value="mqtt">mqtt</option>', page.body)
        result = adapter.handler(TransportRequest(
            'POST', '/maintenance/diagnostics', b'target=mqtt',
            {'role': 'operator', 'csrf_valid': True}
        ))
        self.assertEqual(result.status, 200)
        self.assertEqual(calls, ['mqtt'])
        csrf_denied = adapter.handler(TransportRequest(
            'POST', '/maintenance/diagnostics', b'target=mqtt',
            {'role': 'operator', 'csrf_valid': False}
        ))
        self.assertEqual(csrf_denied.status, 403)
        denied = adapter.handler(TransportRequest(
            'GET', '/maintenance/diagnostics', identity={'role': 'viewer'}
        ))
        self.assertEqual(denied.status, 403)

    def test_device_api_requires_verified_mtls_read_scope(self):
        adapter = Adapter()
        service = DeviceAPIService(
            adapter,
            lambda: {
                'device': 'iot-md-001', 'kernel_state': 'running',
                'health': {'state': 'healthy'}, 'services': [],
            },
            lambda: {'running': True, 'probes': {}},
        )
        service.start()
        self.assertTrue(adapter.mtls)
        denied = adapter.handler(TransportRequest(
            'GET', '/api/v3/device', identity={'verified': False, 'scopes': ['read']}
        ))
        self.assertEqual(denied.status, 403)
        accepted = adapter.handler(TransportRequest(
            'GET', '/api/v3/device',
            identity={'verified': True, 'scopes': ['read']}
        ))
        self.assertEqual(accepted.status, 200)
        self.assertEqual(json.loads(accepted.body)['api_version'], 3)

    def test_navigation_and_forms_share_role_metadata(self):
        viewer_paths = [item['path'] for item in navigation('viewer')]
        admin_paths = [item['path'] for item in navigation('administrator')]
        self.assertNotIn('/maintenance/upgrades', viewer_paths)
        self.assertIn('/maintenance/upgrades', admin_paths)
        self.assertIsNone(form_metadata('diagnostic-run', 'viewer'))
        self.assertEqual(
            form_metadata('diagnostic-run', 'operator')['method'], 'POST'
        )

    def test_standard_factory_keeps_product_services_adapter_driven(self):
        adapters = {
            'wifi': Adapter(), 'mqtt': Adapter(), 'portal': Adapter(),
            'device-api': Adapter(),
        }
        diagnostics = ConnectivityDiagnostics({
            name: (lambda: True) for name in PROBE_NAMES
        })
        factories = build_service_factories(
            adapters, lambda: {'kernel_state': 'running'}, diagnostics
        )
        self.assertEqual(
            set(factories),
            {'wifi', 'mqtt', 'portal', 'device-api', 'connectivity'},
        )
        mqtt = factories['mqtt']({'settings': {'topic_prefix': 'iot-md/test'}})
        mqtt.start()
        self.assertTrue(adapters['mqtt'].started)

    def test_contract_examples_validate(self):
        pairs = (
            ('runtime-configuration.json', 'runtime-configuration.schema.json'),
            ('connectivity-diagnostics.json', 'connectivity-diagnostics.schema.json'),
        )
        for example_name, schema_name in pairs:
            instance = json.loads((
                ROOT / 'v3/contracts/examples' / example_name
            ).read_text())
            schema = json.loads((ROOT / 'v3/contracts' / schema_name).read_text())
            Draft202012Validator(schema).validate(instance)


if __name__ == '__main__':
    unittest.main()
