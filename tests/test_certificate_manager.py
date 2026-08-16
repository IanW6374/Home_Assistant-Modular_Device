import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_private_key

import certificate_manager
import release_update
import web_portal


class CertificateManagerTests(unittest.TestCase):
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
                    certificate_manager.wait_for_http01_mdns('whes01.local', 1)
                ),
                '192.168.1.42'
            )

            certificate_manager._station_address = lambda: ''
            with self.assertRaisesRegex(ValueError, 'connection to the home Wi-Fi'):
                __import__('asyncio').run(
                    certificate_manager.wait_for_http01_mdns('whes01.local', 1)
                )

            with self.assertRaisesRegex(ValueError, r'must end in \.local'):
                __import__('asyncio').run(
                    certificate_manager.wait_for_http01_mdns('whes01.home.arpa', 1)
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
            certificate_manager._csr(private, 'hamd-kitchen.home.arpa')
        )
        self.assertTrue(request.is_signature_valid)
        self.assertEqual(
            request.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value,
            'hamd-kitchen.home.arpa'
        )
        self.assertEqual(
            request.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            .value.get_values_for_type(x509.DNSName),
            ['hamd-kitchen.home.arpa']
        )

    def test_generated_self_signed_certificate_matches_selected_mdns_name(self):
        private = bytes(range(1, 33))
        certificate = x509.load_der_x509_certificate(
            certificate_manager._self_signed_certificate(
                private, 'whes01.local', (2026, 7, 23, 6, 0, 0, 0, 0, 0)
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
            ['whes01.local'],
        )

    def test_installed_certificate_details_decode_safe_identity_fields(self):
        payload = certificate_manager._self_signed_certificate(
            bytes(range(1, 33)), 'whes01.local',
            (2026, 7, 23, 6, 0, 0, 0, 0, 0)
        )
        details = certificate_manager.decode_certificate(payload)
        self.assertEqual(details['subject'], 'CN=whes01.local')
        self.assertEqual(details['issuer'], 'CN=whes01.local')
        self.assertEqual(details['not_before'], '2026-01-01 00:00:00 UTC')
        self.assertEqual(details['not_after'], '2036-12-31 23:59:59 UTC')
        self.assertTrue(details['serial_number'])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'portal.der'
            path.write_bytes(payload)
            installed = certificate_manager.certificate_details(str(path))
            self.assertTrue(installed['installed'])
            self.assertEqual(installed['size'], len(payload))
            self.assertEqual(installed['subject'], 'CN=whes01.local')
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

        certificates = web_portal.render_certificate_page('csrf', certificates={
            'portal': {
                'installed': True, 'subject': 'CN=whes01.local',
                'issuer': 'CN=HAMD CA', 'not_before': '2026-01-01 00:00:00 UTC',
                'not_after': '2027-01-01 00:00:00 UTC', 'serial_number': '01',
                'size': 512,
            },
            'trusted_ca': {'installed': False},
        })
        self.assertIn('/certificate-upload', certificates)
        self.assertIn('/validate-certificates', certificates)
        self.assertIn('Manual certificate upload', certificates)
        self.assertIn('Installed certificates', certificates)
        self.assertIn('CA Trust', certificates)
        self.assertIn('Device Certificates', certificates)
        self.assertLess(certificates.index('CA Trust'), certificates.index('Device Certificates'))
        self.assertIn('CN=whes01.local', certificates)
        self.assertIn('CN=HAMD CA', certificates)
        self.assertIn('not installed', certificates)
        self.assertIn('No separate CA trust anchor is installed.', certificates)
        self.assertIn('self-signed portal certificate is listed under Device Certificates', certificates)


if __name__ == '__main__':
    unittest.main()
