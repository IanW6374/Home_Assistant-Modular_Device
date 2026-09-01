import asyncio
import unittest
from unittest import mock

import network_transports
from network_transports import USBNetwork


class NetworkTransportTests(unittest.TestCase):
    def test_usb_ncm_is_unavailable_without_firmware_class(self):
        with mock.patch.object(network_transports, 'network', object()):
            self.assertFalse(USBNetwork.supported())
            with self.assertRaisesRegex(RuntimeError, 'validated platform capability'):
                asyncio.run(USBNetwork().start())

    def test_runtime_class_alone_does_not_enable_usb_ncm(self):
        class Network:
            class USBD_NCM:
                pass

        with mock.patch.object(network_transports, 'network', Network):
            self.assertFalse(USBNetwork.supported())

    def test_usb_ncm_lifecycle_and_status(self):
        class Interface:
            def __init__(self):
                self.enabled = False

            def active(self, enabled=None):
                if enabled is not None:
                    self.enabled = bool(enabled)
                return self.enabled

            def isconnected(self):
                return self.enabled

            def ipconfig(self, name):
                if name != 'addr4':
                    raise AssertionError(name)
                return '169.254.42.1/16'

        class Network:
            USBD_NCM = Interface

        async def exercise():
            available = {
                'supported': True, 'usb_ncm_available': True,
            }
            with mock.patch.object(network_transports, 'network', Network), \
                    mock.patch.object(
                        network_transports.hardware_platform,
                        'usb_ncm_capability', return_value=available
                    ):
                transport = USBNetwork()
                status = await transport.start()
                self.assertTrue(status['active'])
                self.assertTrue(status['connected'])
                self.assertEqual(status['address'], '169.254.42.1/16')
                await transport.stop()
                self.assertFalse(transport.snapshot()['active'])

        asyncio.run(exercise())


if __name__ == '__main__':
    unittest.main()
