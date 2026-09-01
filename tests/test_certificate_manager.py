import asyncio
import json
import os
import base64
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_private_key

import certificate_manager
import certificate_trust
import release_update
import web_portal


class CertificateManagerTests(unittest.TestCase):
    def test_certificate_lifecycle_uses_30_and_7_day_thresholds(self):
        original = certificate_manager.certificate_details
        certificate_manager.certificate_details = lambda _path: {
            'installed': True,
            'not_after': '2026-02-01 00:00:00 UTC',
        }
        try:
            now = certificate_manager._iso_epoch('2026-01-10 00:00:00 UTC')
            details = certificate_manager.certificate_lifecycle('cert.der', now=now)
            self.assertEqual(details['expiry_level'], 'warning')
            self.assertEqual(details['days_remaining'], 22)
            now = certificate_manager._iso_epoch('2026-01-27 00:00:00 UTC')
            self.assertEqual(
                certificate_manager.certificate_lifecycle('cert.der', now=now)['expiry_level'],
                'critical'
            )
        finally:
            certificate_manager.certificate_details = original

    def test_certificate_set_rolls_back_as_a_unit_when_activation_fails(self):
        previous = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                Path('certs').mkdir()
                Path('certs/web.crt.der').write_bytes(b'old-certificate')
                Path('certs/web.key.der').write_bytes(b'old-key')
                Path('certs/web.crt.der.new').write_bytes(b'new-certificate')
                Path('certs/web.key.der.new').write_bytes(b'new-key')

                def reject():
                    raise ValueError('simulated validation failure')

                with self.assertRaisesRegex(ValueError, 'simulated'):
                    certificate_manager.commit_certificate_files((
                        ('certs/web.crt.der.new', 'certs/web.crt.der'),
                        ('certs/web.key.der.new', 'certs/web.key.der'),
                    ), reject)
                self.assertEqual(
                    Path('certs/web.crt.der').read_bytes(), b'old-certificate'
                )
                self.assertEqual(Path('certs/web.key.der').read_bytes(), b'old-key')
                self.assertFalse(Path(certificate_manager.TRANSACTION_PATH).exists())
            finally:
                os.chdir(previous)

    def test_der_length_does_not_require_bytearray_insert(self):
        class MicroPythonBytearray(bytearray):
            def insert(self, *_args):
                raise AssertionError('bytearray.insert is unavailable on MicroPython')

        original = certificate_manager.bytearray if hasattr(certificate_manager, 'bytearray') else None
        certificate_manager.bytearray = MicroPythonBytearray
        try:
            self.assertEqual(certificate_manager._der_length(127), b'\x7f')
            self.assertEqual(certificate_manager._der_length(128), b'\x81\x80')
            self.assertEqual(certificate_manager._der_length(256), b'\x82\x01\x00')
        finally:
            if original is None:
                del certificate_manager.bytearray
            else:
                certificate_manager.bytearray = original

    def test_acme_response_timeout_names_the_stalled_host(self):
        original = certificate_manager._response_unbounded
        original_timeout = certificate_manager.REQUEST_TIMEOUT_SECONDS

        async def stalled(*_args, **_kwargs):
            await certificate_manager.asyncio.sleep(0.05)

        certificate_manager._response_unbounded = stalled
        certificate_manager.REQUEST_TIMEOUT_SECONDS = 0.001
        try:
            with self.assertRaisesRegex(ValueError, r'ca\.home\.arpa.*timed out'):
                __import__('asyncio').run(certificate_manager._response(
                    'https://ca.home.arpa/acme/directory', 'GET', 'root.der'
                ))
        finally:
            certificate_manager._response_unbounded = original
            certificate_manager.REQUEST_TIMEOUT_SECONDS = original_timeout

    def test_http01_mdns_must_resolve_to_station_address(self):
        original_station = certificate_manager._station_address
        original_getaddrinfo = certificate_manager.socket.getaddrinfo
        original_sleep = certificate_manager.asyncio.sleep

        async def no_wait(_seconds):
            return None

        certificate_manager._station_address = lambda: '192.168.1.42'
        certificate_manager.asyncio.sleep = no_wait
        try:
            def self_lookup_must_not_run(_host, _port):
                raise AssertionError('the device must not resolve its own mDNS name')

            certificate_manager.socket.getaddrinfo = self_lookup_must_not_run
            self.assertEqual(
                __import__('asyncio').run(
                    certificate_manager.wait_for_http01_mdns('iot-md-001.local', 1)
                ),
                '192.168.1.42'
            )

            certificate_manager._station_address = lambda: ''
            with self.assertRaisesRegex(ValueError, 'connection to the home Wi-Fi'):
                __import__('asyncio').run(
                    certificate_manager.wait_for_http01_mdns('iot-md-001.local', 1)
                )

            with self.assertRaisesRegex(ValueError, r'must end in \.local'):
                __import__('asyncio').run(
                    certificate_manager.wait_for_http01_mdns('iot-md-001.home.arpa', 1)
                )
        finally:
            certificate_manager._station_address = original_station
            certificate_manager.socket.getaddrinfo = original_getaddrinfo
            certificate_manager.asyncio.sleep = original_sleep

    def test_generated_ec_key_and_csr_are_standard_der(self):
        private = bytes(range(1, 33))
        key = load_der_private_key(certificate_manager._ec_private_key_der(private), None)
        self.assertEqual(key.key_size, 256)

        request = x509.load_der_x509_csr(
            certificate_manager._csr(private, 'iotmd-kitchen.home.arpa')
        )
        self.assertTrue(request.is_signature_valid)
        self.assertEqual(
            request.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value,
            'iotmd-kitchen.home.arpa'
        )
        self.assertEqual(
            request.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            .value.get_values_for_type(x509.DNSName),
            ['iotmd-kitchen.home.arpa']
        )

    def test_generated_self_signed_certificate_matches_selected_mdns_name(self):
        private = bytes(range(1, 33))
        certificate = x509.load_der_x509_certificate(
            certificate_manager._self_signed_certificate(
                private, 'iot-md-001.local', (2026, 7, 23, 6, 0, 0, 0, 0, 0)
            )
        )
        key = load_der_private_key(
            certificate_manager._ec_private_key_der(private), None
        )
        key.public_key().verify(
            certificate.signature,
            certificate.tbs_certificate_bytes,
            ec.ECDSA(certificate.signature_hash_algorithm),
        )
        self.assertEqual(certificate.subject, certificate.issuer)
        self.assertEqual(
            certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            .value.get_values_for_type(x509.DNSName),
            ['iot-md-001.local'],
        )

    def test_installed_certificate_details_decode_safe_identity_fields(self):
        payload = certificate_manager._self_signed_certificate(
            bytes(range(1, 33)), 'iot-md-001.local',
            (2026, 7, 23, 6, 0, 0, 0, 0, 0)
        )
        details = certificate_manager.decode_certificate(payload)
        self.assertEqual(details['subject'], 'CN=iot-md-001.local')
        self.assertEqual(details['issuer'], 'CN=iot-md-001.local')
        self.assertEqual(details['not_before'], '2026-01-01 00:00:00 UTC')
        self.assertEqual(details['not_after'], '2036-12-31 23:59:59 UTC')
        self.assertTrue(details['serial_number'])
        pem_chain = (
            b'-----BEGIN CERTIFICATE-----\n' + base64.b64encode(payload) +
            b'\n-----END CERTIFICATE-----\n' +
            b'-----BEGIN CERTIFICATE-----\n' + base64.b64encode(payload) +
            b'\n-----END CERTIFICATE-----\n'
        )
        pem_details = certificate_manager.decode_certificate(pem_chain)
        self.assertEqual(pem_details['subject'], 'CN=iot-md-001.local')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'portal.der'
            path.write_bytes(payload)
            installed = certificate_manager.certificate_details(str(path))
            self.assertTrue(installed['installed'])
            self.assertEqual(installed['size'], len(payload))
            self.assertEqual(installed['subject'], 'CN=iot-md-001.local')
            self.assertFalse(
                certificate_manager.certificate_details(str(path) + '.missing')['installed']
            )

    def test_renewal_starts_after_two_thirds_of_lifetime(self):
        previous = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                Path('certs').mkdir()
                Path(certificate_manager.STATE_PATH).write_text(json.dumps({
                    'not_before': '2026-07-22T00:00:00Z',
                    'not_after': '2026-07-23T00:00:00Z',
                }))
                start = certificate_manager._iso_epoch('2026-07-22T00:00:00Z')
                self.assertFalse(certificate_manager.renewal_due(start + 15 * 3600))
                self.assertTrue(certificate_manager.renewal_due(start + 16 * 3600))
            finally:
                os.chdir(previous)

    def test_self_signed_monitor_regenerates_due_identity(self):
        resets = []
        logs = []

        async def no_wait(_seconds):
            return None

        with (
            mock.patch.object(certificate_manager, 'renewal_due', return_value=True),
            mock.patch.object(
                certificate_manager, 'install_self_signed',
                return_value={'not_after': '2037-12-31T23:59:59Z'},
            ),
            mock.patch.object(certificate_manager.asyncio, 'sleep', no_wait),
        ):
            asyncio.run(certificate_manager.self_signed_renewal_monitor(
                {'hostname': 'iot-md-001.local'},
                lambda *args: logs.append(args),
                lambda: resets.append(True),
            ))

        self.assertEqual(resets, [True])
        self.assertIn('Renewed until 2037-12-31T23:59:59Z', logs[0][2]['log'])

    def test_certificate_page_names_every_method_and_warns_for_manual(self):
        methods = (
            ('self_signed', 'self_signed', 'Self-signed device certificate'),
            ('iot_ca', 'iot_ca_auto', 'Automatic IoT CA enrollment'),
            ('iot_ca', 'iot_ca_file', 'IoT CA enrollment authorization (.iotenroll)'),
            ('acme', 'acme', 'Private CA ACME enrollment'),
            ('manual', 'manual', 'Manual certificate package'),
        )
        for mode, method, name in methods:
            html = web_portal.render_certificate_page(
                'csrf', certificates={'acme_settings': {
                    'mode': mode, 'method': method,
                }}
            )
            self.assertIn(name, html)
            self.assertIn('Current enrollment', html)
        manual = web_portal.render_certificate_page(
            'csrf', certificates={'acme_settings': {'mode': 'manual'}}
        )
        self.assertIn('Automatic renewal is unavailable', manual)

    def test_component_applicability_only_uses_configured_modules(self):
        components = {
            'runtime': 4,
            'modules': {'whes': 8, 'ems': 3},
        }
        installed = {'whes': 7, 'ems': 2}
        self.assertFalse(release_update.application_release_applicable(
            components, (), 4, installed
        ))
        self.assertTrue(release_update.application_release_applicable(
            components, ('whes',), 4, installed
        ))
        self.assertFalse(release_update.application_release_applicable(
            {'runtime': 4, 'modules': {'whes': 7, 'ems': 3}},
            ('whes',), 4, installed
        ))
        self.assertTrue(release_update.application_release_applicable(
            {'runtime': 5, 'modules': {'whes': 7}},
            (), 4, installed
        ))

    def test_portal_exposes_module_editor_and_manual_certificate_fallback(self):
        modules = web_portal.render_module_settings_page(
            'csrf', '{"devices":[]}'
        )
        self.assertIn('name="module_settings_json"', modules)
        self.assertIn('id="module-settings-file"', modules)
        self.assertIn('Verify and apply configuration', modules)

        details = {
            'portal': {
                'installed': True, 'subject': 'CN=iot-md-001.local',
                'issuer': 'CN=IoTMD CA', 'not_before': '2026-01-01 00:00:00 UTC',
                'not_after': '2027-01-01 00:00:00 UTC', 'serial_number': '01',
                'size': 512,
            },
            'trusted_ca': {'installed': False},
        }
        identities = web_portal.render_certificate_route(
            '/device-certificates', 'csrf', certificates=details
        )
        enrollment = web_portal.render_certificate_route(
            '/certificates', 'csrf', certificates=details
        )
        api_trust = web_portal.render_certificate_route(
            '/api-client-trust', 'csrf', certificates=details
        )
        ca_trust = web_portal.render_certificate_route(
            '/certificate-authorities', 'csrf', certificates=details
        )
        self.assertNotIn('/certificate-upload', identities)
        self.assertNotIn('/validate-certificates', identities)
        self.assertNotIn('Manual identity installation', identities)
        self.assertIn('Device API and fleet server identity', identities)
        self.assertIn('MQTT, upgrade and syslog connections', identities)
        self.assertIn('/certificate-upload', enrollment)
        self.assertIn('/validate-certificates', enrollment)
        self.assertIn('Manual certificate package', enrollment)
        self.assertIn('Device API and fleet server identity', enrollment)
        self.assertIn('value="fleet-client-cert"', api_trust)
        self.assertIn('value="management-suite-key"', ca_trust)
        self.assertIn('MQTT broker CA', ca_trust)
        self.assertIn('Release server CA', ca_trust)
        self.assertIn('Syslog server CA', ca_trust)
        self.assertIn('CN=iot-md-001.local', identities)
        self.assertIn('CN=IoTMD CA', identities)
        self.assertIn('not installed', ca_trust)

    def test_replaceable_ca_and_exact_api_client_trust_can_be_removed(self):
        class APITrust:
            def __init__(self):
                self.revoked = []

            def revoke(self, fingerprint):
                self.revoked.append(fingerprint)
                return fingerprint == 'aabb'

        api_trust = APITrust()
        with tempfile.TemporaryDirectory() as directory:
            mqtt_ca = Path(directory) / 'mqtt-ca.der'
            mqtt_ca.write_bytes(b'certificate')
            message, reload_api = certificate_trust.remove(
                'mqtt-ca', '', api_trust, {'mqtt-ca': str(mqtt_ca)}
            )
            self.assertEqual(message, 'MQTT broker CA removed')
            self.assertFalse(reload_api)
            self.assertFalse(mqtt_ca.exists())

        message, reload_api = certificate_trust.remove(
            'api-client-ca', 'AA:BB'.replace(':', ''), api_trust, {}
        )
        self.assertEqual(message, 'Device API client issuer CA removed')
        self.assertTrue(reload_api)
        self.assertEqual(api_trust.revoked, ['aabb'])


if __name__ == '__main__':
    unittest.main()
