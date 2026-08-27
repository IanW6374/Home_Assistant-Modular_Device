import asyncio
import base64
import builtins
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import ExtendedKeyUsageOID

import iot_ca_enrollment


class IoTCAEnrollmentTests(unittest.TestCase):
    def package(self, api_hostname='device.local'):
        return json.dumps({
            'protocol': 'iotmd-enrollment-v1',
            'enrollment_id': 'enrollment-1',
            'endpoint': 'https://iot-ca.home.arpa:9010',
            'token': 'one-time-secret',
            'portal_hostname': 'device.example.com',
            'api_hostname': api_hostname,
            'renewal_name': 'iotmd-renewal-enrollment-1',
            'ca_root_der': base64.b64encode(b'fake-root').decode(),
            'expires_at': '2099-01-01T00:00:00Z',
        }).encode()

    def test_package_is_bound_to_configured_device_hostname(self):
        with self.assertRaisesRegex(ValueError, 'another device hostname'):
            iot_ca_enrollment._package(self.package(), 'other.local')

    def test_dns_failure_is_reported_with_endpoint_context(self):
        error = OSError(-202)
        self.assertEqual(
            iot_ca_enrollment._failure_message(
                error, 'https://iot-ca.home.arpa:9010/v1/enrollments/one'
            ),
            'Could not resolve the IoT CA server (iot-ca.home.arpa:9010). '
            'Check the CA DNS name and the DNS server supplied to this device.',
        )

    def test_frozen_first_boot_import_does_not_require_application_logging(self):
        source = Path(iot_ca_enrollment.__file__)
        specification = importlib.util.spec_from_file_location(
            'frozen_iot_ca_enrollment_test', source
        )
        module = importlib.util.module_from_spec(specification)
        real_import = builtins.__import__

        def without_application(name, *args, **kwargs):
            if name == 'device_modules' or name.startswith('device_modules.'):
                raise ImportError('application slot is not mounted')
            return real_import(name, *args, **kwargs)

        with mock.patch('builtins.__import__', side_effect=without_application):
            specification.loader.exec_module(module)

        self.assertEqual(module.PROTOCOL, 'iotmd-enrollment-v1')

    def test_frozen_failure_logging_falls_back_to_usb_console(self):
        real_import = builtins.__import__

        def without_application(name, *args, **kwargs):
            if name == 'device_modules.logging':
                raise ImportError('application slot is not mounted')
            return real_import(name, *args, **kwargs)

        with (
            mock.patch('builtins.__import__', side_effect=without_application),
            mock.patch('builtins.print') as output,
        ):
            iot_ca_enrollment._log_failure(
                'IoT CA auto enrollment', OSError(-202)
            )

        output.assert_called_once_with(
            'ERROR IoT CA auto enrollment: Failed - -202'
        )

    def test_automatic_package_is_host_bound_and_uses_bootstrap_only_once(self):
        async def scenario():
            calls = []

            async def response(url, method, ca_path, body=b'', content_type='',
                               accept='', extra_headers=(), tls_context=None):
                calls.append((
                    url, method, ca_path, json.loads(body), content_type,
                    tls_context.verify_mode,
                ))
                return 201, {}, self.package()

            with mock.patch.object(
                iot_ca_enrollment.certificate_manager, '_response', response
            ):
                payload = await iot_ca_enrollment.automatic_package(
                    'homeassistant.local', 'device.local'
                )
            self.assertEqual(json.loads(payload)['api_hostname'], 'device.local')
            self.assertEqual(calls[0][0], (
                'https://homeassistant.local:9010/v1/auto-enrollments'
            ))
            self.assertEqual(calls[0][1:5], (
                'POST', '', {'api_hostname': 'device.local'}, 'application/json'
            ))
            self.assertEqual(calls[0][5], iot_ca_enrollment.ssl.CERT_NONE)

        asyncio.run(scenario())

    def test_automatic_server_rejects_urls_and_invalid_labels(self):
        self.assertEqual(
            iot_ca_enrollment._auto_server('HomeAssistant.Local.'),
            'homeassistant.local',
        )
        for value in ('https://homeassistant.local', '-ca.local', 'ca..local'):
            with self.assertRaisesRegex(ValueError, 'server name is invalid'):
                iot_ca_enrollment._auto_server(value)

    def test_device_generates_three_distinct_usage_bound_csrs_and_keeps_keys(self):
        async def scenario():
            requests = []

            async def response(url, method, ca_path, body=b'', content_type='',
                               accept='', extra_headers=()):
                requests.append((url, method, ca_path, body, extra_headers))
                issued = {
                    'protocol': 'iotmd-enrollment-v1',
                    'portal_hostname': 'device.example.com',
                    'api_hostname': 'device.local',
                    'portal_certificate_pem': base64.b64encode(b'portal-chain').decode(),
                    'api_certificate_pem': base64.b64encode(b'api-chain').decode(),
                    'renewal_certificate_der': base64.b64encode(b'renewal-certificate').decode(),
                    'portal_not_after': '2098-12-01T00:00:00Z',
                }
                return 200, {}, json.dumps({
                    'status': 'complete', 'result': issued,
                }).encode()

            with tempfile.TemporaryDirectory() as directory:
                previous = os.getcwd()
                os.chdir(directory)
                try:
                    Path('certs/trust').mkdir(parents=True)
                    paths = {
                        'trust-ca': 'certs/trust/root.der',
                        'portal-cert': 'certs/web.crt.der',
                        'portal-key': 'certs/web.key.der',
                        'api-server-cert': 'certs/api.crt.der',
                        'api-server-key': 'certs/api.key.der',
                    }
                    with mock.patch.object(
                        iot_ca_enrollment.certificate_manager, '_response', response
                    ):
                        result = await iot_ca_enrollment.enroll(
                            self.package(), 'device.local', paths
                        )
                    submitted = json.loads(requests[0][3])
                    portal = x509.load_der_x509_csr(
                        base64.b64decode(submitted['portal_csr'])
                    )
                    api = x509.load_der_x509_csr(
                        base64.b64decode(submitted['api_csr'])
                    )
                    renewal = x509.load_der_x509_csr(
                        base64.b64decode(submitted['renewal_csr'])
                    )
                    for request in (portal, api, renewal):
                        self.assertTrue(request.is_signature_valid)
                    self.assertIn(
                        ExtendedKeyUsageOID.SERVER_AUTH,
                        portal.extensions.get_extension_for_class(
                            x509.ExtendedKeyUsage
                        ).value,
                    )
                    self.assertIn(
                        ExtendedKeyUsageOID.SERVER_AUTH,
                        api.extensions.get_extension_for_class(
                            x509.ExtendedKeyUsage
                        ).value,
                    )
                    self.assertIn(
                        ExtendedKeyUsageOID.CLIENT_AUTH,
                        renewal.extensions.get_extension_for_class(
                            x509.ExtendedKeyUsage
                        ).value,
                    )
                    with self.assertRaises(x509.ExtensionNotFound):
                        renewal.extensions.get_extension_for_class(
                            x509.SubjectAlternativeName
                        )
                    public_keys = {
                        request.public_key().public_bytes(
                            serialization.Encoding.X962,
                            serialization.PublicFormat.UncompressedPoint,
                        ) for request in (portal, api, renewal)
                    }
                    self.assertEqual(len(public_keys), 3)
                    self.assertNotIn('one-time-secret', str(result))
                    self.assertEqual(len(result['pairs']), 8)
                    self.assertEqual(
                        requests[0][4],
                        (('Authorization', 'Bearer one-time-secret'),),
                    )
                finally:
                    os.chdir(previous)

        asyncio.run(scenario())


if __name__ == '__main__':
    unittest.main()
