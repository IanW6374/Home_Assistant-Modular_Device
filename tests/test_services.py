import unittest

from services.messaging_service import MessagingService
from services.network_service import NetworkService
from services.portal_service import PortalService
from services.update_service import UpdateService
from services.event_sinks import LegacyLogSink


class ServiceBoundaryTests(unittest.TestCase):
    def test_structured_event_log_sink_maps_severity(self):
        entries = []
        LegacyLogSink(lambda *args: entries.append(args)).write({
            'component': 'update', 'kind': 'verified',
            'message': 'ready', 'severity': 'warning',
        })
        self.assertEqual(entries[0][0:2], ('Local', 'update verified'))
        self.assertEqual(entries[0][3], 'INFO')

    def test_network_and_messaging_adapters_copy_external_state(self):
        status = {'connected': True}
        network = NetworkService(lambda: status, lambda: [{'ssid': 'one'}])
        self.assertEqual(network.status(), status)
        self.assertIsNot(network.status(), status)
        sent = []
        messaging = MessagingService(lambda *args: sent.append(args))
        messaging.publish('state/topic', 'on', True, 1)
        self.assertEqual(sent[0], ('state/topic', 'on', True, 1))

    def test_update_service_selects_only_declared_receivers(self):
        class Store:
            def begin(self, *args):
                return args
            def status(self, value):
                return {'id': value}
        async def receiver(_reader, _length, _params):
            return 'ready'
        service = UpdateService(
            Store(), {'application': receiver}, lambda: {'ready': False}
        )
        self.assertIs(service.receiver('application'), receiver)
        with self.assertRaisesRegex(ValueError, 'invalid'):
            service.receiver('unknown')

    def test_portal_service_tracks_listener(self):
        async def starter():
            return 'listener'
        service = PortalService(starter)
        import asyncio
        self.assertEqual(asyncio.run(service.start()), 'listener')


if __name__ == '__main__':
    unittest.main()
