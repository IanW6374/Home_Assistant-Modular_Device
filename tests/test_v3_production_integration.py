import asyncio
import json
import unittest

from v3.runtime.iotmd_next.identity import IdentityLifecycleService
from v3.runtime.iotmd_next.production_adapters import (
    AsyncOperationTracker, ProductionListenerAdapter,
    ProductionMQTTAdapter, ProductionSyslogAdapter, ProductionWiFiAdapter,
)
from v3.runtime.iotmd_next.production_identity import (
    OpaqueHandleRegistry, ProductionIdentityAdapter,
)


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


class Station:
    def __init__(self):
        self.enabled = False
        self.connected = False

    def active(self, value=None):
        if value is not None:
            self.enabled = bool(value)
        return self.enabled

    def isconnected(self):
        return self.connected

    def disconnect(self):
        self.connected = False

    def ifconfig(self):
        return ('192.0.2.10', '255.255.255.0', '192.0.2.1', '192.0.2.1')


class MQTTClient:
    def __init__(self):
        self.messages = []

    async def connect(self):
        return None

    async def disconnect(self):
        return None

    async def publish(self, topic, payload, retain=False, qos=0):
        self.messages.append((topic, payload, retain, qos))


class Remote:
    active = True

    def __init__(self):
        self.messages = []

    async def run(self):
        return None

    def enqueue(self, timestamp, message, severity, audit):
        self.messages.append((timestamp, message, severity, audit))
        return True

    def status(self):
        return {'queued': len(self.messages), 'delivered': 0,
                'failures': 0, 'last_error': ''}


class V3ProductionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_production_transport_bridges_track_real_async_lifecycles(self):
        station = Station()
        tracker = AsyncOperationTracker(asyncio.create_task)

        async def connect(settings):
            self.assertEqual(settings['ssid'], 'test')
            station.connected = True

        wifi = ProductionWiFiAdapter(
            station, {'ssid': 'test'}, lambda target, settings: None,
            connect, tracker, lambda: 1000,
        )
        wifi.start()
        await asyncio.sleep(0)
        self.assertEqual(wifi.status()['state'], 'online')

        mqtt_client = MQTTClient()
        mqtt = ProductionMQTTAdapter(
            mqtt_client, AsyncOperationTracker(asyncio.create_task)
        )
        mqtt.connect()
        mqtt.publish('iot-md/test', 'online', True, 1)
        await asyncio.sleep(0)
        self.assertEqual(mqtt_client.messages[0][0], 'iot-md/test')

        listeners = []

        async def start_listener(handler, require_mtls=False):
            value = {'handler': handler, 'mtls': require_mtls}
            listeners.append(value)
            return value

        listener = ProductionListenerAdapter(
            start_listener, lambda value: listeners.remove(value),
            AsyncOperationTracker(asyncio.create_task),
        )
        listener.start(lambda request: request, require_mtls=True)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(listener.status()['state'], 'online')
        self.assertTrue(listener.status()['mtls'])

        remote = Remote()
        syslog = ProductionSyslogAdapter(
            remote, AsyncOperationTracker(asyncio.create_task)
        )
        syslog.start()
        self.assertTrue(syslog.emit('-', 'boot complete', 'INFO', False))
        await asyncio.sleep(0)
        self.assertEqual(syslog.status()['queued'], 1)

    async def test_identity_uses_real_inventory_with_opaque_stable_handles(self):
        namespace = MemoryNamespace()
        handles = OpaqueHandleRegistry(namespace)
        method = ['automatic-iot-ca']
        certificates = {
            '/certs/portal.der': {
                'installed': True, 'subject': 'CN=iot-md-001.local',
                'issuer': 'CN=Home IoT CA', 'not_before': '1000',
                'not_after': '4000',
            },
        }
        trusts = [{
            'id': 'mqtt-root', 'purpose': 'mqtt', 'subject': 'MQTT root',
            'fingerprint': 'b' * 64, 'generation': 7,
        }]

        def enroll(selected, authorization):
            method[0] = selected

        def remove(identifier, generation):
            trusts[:] = [item for item in trusts if item['id'] != identifier]

        adapter = ProductionIdentityAdapter(
            {'portal': {'certificate': '/certs/portal.der',
                        'key': '/certs/portal.key'}},
            lambda path: dict(certificates.get(path, {'installed': False})),
            lambda path: 'a' * 64, lambda: method[0], enroll,
            lambda selected: None, lambda: [dict(item) for item in trusts],
            remove, handles, lambda value: int(value), lambda: 2000,
        )
        service = IdentityLifecycleService(
            adapter, {
                'enabled': True, 'method': 'automatic-iot-ca',
                'critical': True, 'dependencies': ['wifi'],
                'renewal_check_s': 60,
            }, lambda: 2000, lambda: True,
        )
        service.start()
        first = service.inventory()
        second = adapter.identity_state()
        self.assertEqual(
            first['identities'][0]['certificate_handle'],
            second['identities'][0]['certificate_handle'],
        )
        self.assertNotIn('/certs/', json.dumps(first))
        with self.assertRaisesRegex(RuntimeError, 'generation'):
            service.remove_trust('mqtt-root', 6)
        self.assertEqual(service.remove_trust('mqtt-root', 7), [])

    async def test_failed_identity_method_change_does_not_latch_requested_method(self):
        def fail_enrollment(method, authorization):
            raise RuntimeError('enrollment failed')

        adapter = ProductionIdentityAdapter(
            {'portal': {'certificate': '/certs/portal.der',
                        'key': '/certs/portal.key'}},
            lambda path: {'installed': False}, lambda path: 'a' * 64,
            lambda: 'self-signed', fail_enrollment, lambda method: None,
            lambda: [], lambda identifier, generation: None,
            OpaqueHandleRegistry(MemoryNamespace()), lambda value: int(value),
            lambda: 2000,
        )
        adapter.start()
        with self.assertRaisesRegex(RuntimeError, 'enrollment failed'):
            adapter.enroll('automatic-iot-ca', None)
        self.assertEqual(adapter.identity_state()['method'], 'self-signed')
