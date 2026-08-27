import asyncio
import unittest
from unittest import mock

import certificate_lifecycle


class CertificateLifecycleTests(unittest.TestCase):
    def test_each_managed_method_starts_its_named_renewal_strategy(self):
        paths = {'trust-ca': 'root.der'}
        for mode, target in (
            ('acme', certificate_lifecycle.certificate_manager),
            ('iot_ca', certificate_lifecycle.iot_ca_enrollment),
            ('self_signed', certificate_lifecycle.certificate_manager),
        ):
            function = (
                'renewal_monitor' if mode != 'self_signed'
                else 'self_signed_renewal_monitor'
            )
            with mock.patch.object(
                target, function, new_callable=mock.AsyncMock
            ) as selected:
                asyncio.run(certificate_lifecycle.monitor(
                    {'mode': mode}, paths, lambda *_args: None,
                    lambda: None, lambda: None,
                ))
            selected.assert_awaited_once()

    def test_manual_package_warns_and_starts_no_renewal_service(self):
        logs = []
        asyncio.run(certificate_lifecycle.monitor(
            {'mode': 'manual'}, {}, lambda *args: logs.append(args),
            lambda: None, lambda: None,
        ))
        self.assertEqual(logs[0][1], 'Manual certificate package')
        self.assertIn('Automatic renewal is unavailable', logs[0][2]['log'])
        self.assertTrue(logs[0][2]['force'])


if __name__ == '__main__':
    unittest.main()
