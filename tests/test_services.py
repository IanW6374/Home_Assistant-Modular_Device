import unittest

from services.messaging_service import MessagingService
from services.network_service import NetworkService
from services.portal_service import PortalService
from services.update_service import UpdateService


class ServiceBoundaryTests(unittest.TestCase):
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
        receiver = object()
        service = UpdateService(Store(), receiver, None, None, lambda: {'ready': False})
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
