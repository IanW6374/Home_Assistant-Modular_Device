import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import api_security
import certificate_manager
import device_api
from device_api import DeviceAPI
from runtime_health import HealthHistory


def client_certificate(common_name='automation-client.local'):
    original_time = certificate_manager.time

    class FixedTime:
        @staticmethod
        def localtime():
            return (2026, 1, 1, 0, 0, 0, 0, 1)

    certificate_manager.time = FixedTime()
    try:
        return certificate_manager._self_signed_certificate(
            bytes(range(1, 33)), common_name
        )
    finally:
        certificate_manager.time = original_time


class FakeBroker:
    def __init__(self):
        self.commands = []

    def catalog(self):
        return [{'uuid': '0001', 'name': 'Boiler'}]

    def state(self, uuid):
        if uuid != '0001':
            raise KeyError(uuid)
        return {'temperature': 55}

    def diagnostics(self, uuid):
        return {'last_ok': True}

    def submit(self, uuid, command, source, identity):
        self.commands.append((uuid, command, source, identity))
        return {'id': command.get('request_id', 'generated'), 'status': 'queued'}

    def operation(self, operation_id):
        return {'id': operation_id, 'status': 'complete'} if operation_id == 'known' else None


class DeviceAPITests(unittest.TestCase):
    def test_v1_namespace_is_not_exposed_by_clean_seed_runtime(self):
        self.registry.enrol(self.cert, 'reader', ('read',))
        status, body = self.api.dispatch(
            'GET', '/api/v1/modules', b'', self.cert
        )
        self.assertEqual(status, 404)
        self.assertEqual(body['error'], 'endpoint not found')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        registry_path = str(Path(self.temp.name) / 'clients.json')
        self.registry = api_security.ClientRegistry(registry_path)
        self.cert = client_certificate()
        self.health = HealthHistory(str(Path(self.temp.name) / 'health.json'))
        self.broker = FakeBroker()
        self.api = DeviceAPI(
            self.broker, self.health, self.registry,
            lambda: {'device_name': 'test'}
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_read_scoped_client_can_read_but_not_write(self):
        record = self.registry.enrol(self.cert, 'reader', ('read',))
        self.assertEqual(len(record['fingerprint']), 64)
        listed = self.registry.list_clients()[0]
        self.assertIn(listed['expiry_level'], ('ok', 'unknown'))
        self.assertIn('days_remaining', listed)

        status, payload = self.api.dispatch(
            'GET', '/api/v2/modules/0001/state', b'', self.cert
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload['state']['temperature'], 55)

        with self.assertRaisesRegex(PermissionError, 'write scope'):
            self.api.dispatch(
                'POST', '/api/v2/modules/0001/commands', b'{"value":1}', self.cert
            )

    def test_write_client_submits_same_json_command_contract(self):
        self.registry.enrol(self.cert, 'controller', ('read', 'write'))

        status, operation = self.api.dispatch(
            'POST', '/api/v2/modules/0001/commands',
            b'{"request_id":"abc","operation":"write","value":20}',
            self.cert
        )

        self.assertEqual(status, 202)
        self.assertEqual(operation['id'], 'abc')
        self.assertEqual(self.broker.commands[0][1]['operation'], 'write')
        self.assertEqual(self.broker.commands[0][2], 'api')

    def test_unenrolled_certificate_is_rejected(self):
        with self.assertRaisesRegex(PermissionError, 'not enrolled'):
            self.api.dispatch('GET', '/api/v2/device/inventory', b'', self.cert)

    def test_revoked_certificate_is_rejected(self):
        record = self.registry.enrol(self.cert, 'reader', ('read',))
        self.assertTrue(self.registry.revoke(record['fingerprint']))
        with self.assertRaises(PermissionError):
            self.api.dispatch('GET', '/api/v2/device/inventory', b'', self.cert)

    def test_registry_creates_nested_absolute_directory(self):
        path = Path(self.temp.name) / 'nested' / 'certs' / 'clients.json'
        registry = api_security.ClientRegistry(str(path))

        registry.enrol(self.cert, 'reader', ('read',))

        self.assertTrue(path.is_file())

    def test_v1_registry_is_rejected_by_clean_seed_runtime(self):
        path = Path(self.temp.name) / 'legacy-clients.json'
        fingerprint = api_security.certificate_fingerprint(self.cert)
        path.write_text(json.dumps({
            'format_version': 1,
            'clients': [{
                'fingerprint': fingerprint,
                'label': 'v1 automation',
                'scopes': ['read', 'write'],
                'subject': 'automation-client.local',
                'issuer': 'automation-client.local',
                'not_after': '',
            }],
        }))
        registry = api_security.ClientRegistry(str(path))

        with self.assertRaisesRegex(ValueError, 'invalid format'):
            registry.list_clients()

    def test_invalid_module_uuid_returns_json_404(self):
        self.registry.enrol(self.cert, 'reader', ('read',))

        status, payload = self.api.dispatch(
            'GET', '/api/v2/modules/ffff/state', b'', self.cert
        )

        self.assertEqual(status, 404)
        self.assertEqual(payload['module'], 'ffff')
        self.assertEqual(self.health.snapshot()['counters']['api_requests'], 1)
        self.assertEqual(self.health.snapshot()['counters']['api_failures'], 1)
        self.assertEqual(self.health.snapshot()['events'][-1]['kind'], 'api_not_found')

    def test_multiple_independent_api_ca_trusts_are_stored(self):
        store = api_security.CATrustStore(
            str(Path(self.temp.name) / 'trust'), maximum=4
        )
        first = client_certificate('first-ca.local')
        second = client_certificate('second-ca.local')

        store.add(first)
        store.add(second)

        self.assertEqual(len(store.paths()), 2)
        self.assertEqual(len(store.list()), 2)

    def test_server_completes_deferred_tls_handshake_before_reading_peer_certificate(self):
        self.registry.enrol(self.cert, 'reader', ('read',))

        class TLSStream:
            def __init__(stream_self):
                stream_self.handshake_complete = False

            def getpeercert(stream_self, binary_form=False):
                if not stream_self.handshake_complete:
                    raise RuntimeError('certificate inspected before TLS handshake')
                return self.cert

        class Reader:
            def __init__(stream_self):
                stream_self.s = TLSStream()
                stream_self.data = (
                    b'GET /api/v2/modules HTTP/1.1\r\n'
                    b'Connection: close\r\n\r\n'
                )

            async def read(stream_self, size):
                stream_self.s.handshake_complete = True
                value, stream_self.data = (
                    stream_self.data[:size], stream_self.data[size:]
                )
                return value

        class Writer:
            def __init__(stream_self):
                stream_self.payload = bytearray()

            def write(stream_self, payload):
                stream_self.payload.extend(payload)

            async def drain(stream_self):
                pass

            def close(stream_self):
                pass

            async def wait_closed(stream_self):
                pass

        async def exercise():
            captured = {}

            async def capture_server(handler, *_args, **_kwargs):
                captured['handler'] = handler
                return object()

            with mock.patch.object(device_api, 'make_mtls_context', return_value=object()), \
                    mock.patch.object(device_api.asyncio, 'start_server', side_effect=capture_server):
                await device_api.start_device_api({
                    'enabled': True, 'cert_path': 'server.der',
                    'key_path': 'server-key.der', 'client_ca_path': 'ca.der',
                }, self.api)
            reader = Reader()
            writer = Writer()
            await captured['handler'](reader, writer)
            self.assertTrue(reader.s.handshake_complete)
            self.assertIn(b'HTTP/1.1 200 OK', writer.payload)

        asyncio.run(exercise())

    def test_v2_inventory_events_and_support_endpoints(self):
        self.registry.enrol(self.cert, 'dashboard', ('read',))
        self.health.record_event('boot_complete', component='startup')
        self.api.support_getter = lambda: {
            'format_version': 1, 'redaction': 'verified'
        }

        status, inventory = self.api.dispatch(
            'GET', '/api/v2/device/inventory', b'', self.cert
        )
        self.assertEqual(status, 200)
        self.assertEqual(inventory['api_version'], 2)
        self.assertEqual(inventory['modules'][0]['uuid'], '0001')

        status, events = self.api.dispatch(
            'GET', '/api/v2/events?cursor=0&limit=1', b'', self.cert
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(events['events']), 1)

        status, support = self.api.dispatch(
            'GET', '/api/v2/support', b'', self.cert
        )
        self.assertEqual(status, 200)
        self.assertEqual(support['redaction'], 'verified')

    def test_restful_fleet_command_result_uses_path_identifier(self):
        class Fleet:
            def snapshot(fleet_self):
                return {'pending_commands': [{'id': 'command-7'}]}

            def complete_command(fleet_self, identifier, result, detail):
                self.assertEqual(identifier, 'command-7')
                return {'completed': identifier, 'result': result}

        registry_path = str(Path(self.temp.name) / 'fleet-clients.json')
        registry = api_security.ClientRegistry(registry_path)
        registry.enrol(self.cert, 'fleet', ('fleet:read', 'fleet:write'))
        api = DeviceAPI(
            self.broker, self.health, registry,
            lambda: {'device_name': 'test'}, fleet=Fleet()
        )
        status, result = api.dispatch(
            'POST', '/api/v2/fleet/commands/command-7/result',
            b'{"result":"complete"}', self.cert
        )
        self.assertEqual(status, 200)
        self.assertEqual(result['completed'], 'command-7')


if __name__ == '__main__':
    unittest.main()
