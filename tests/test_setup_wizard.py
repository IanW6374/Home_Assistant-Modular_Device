import json
import asyncio
import unittest
from pathlib import Path
from unittest import mock

import credential_security
import credential_store
import setup_wizard
import setup_workflow
import setup_wizard_views
import web_portal_ui
import wifi_recovery


class SetupWizardTests(unittest.TestCase):
    def setUp(self):
        credential_store._reset_memory_backend()

    def tearDown(self):
        credential_store._reset_memory_backend()

    def fields(self):
        return {
            'device_name': 'Boiler controller',
            'wifi_ssid': 'home-network',
            'wifi_password': 'wifi-password',
            'mqtt_server': 'mqtt.home.arpa',
            'mqtt_port': '8883',
            'mqtt_username': 'device-user',
            'mqtt_password': 'mqtt-secret',
            'mqtt_ssl': True,
            'portal_username': 'admin',
            'recovery_ap_password': 'Recovery-Access-Cedar-47!',
            'recovery_ap_password_confirm': 'Recovery-Access-Cedar-47!',
            'channel': 'stable',
            'certificate_hostname': 'whes01.local',
        }

    def test_wizard_and_portal_share_visual_foundations(self):
        for rule in (
            '--accent:#087e8b',
            'main{width:auto;margin:0 clamp(16px,4vw,38px)',
            '.topbar{position:sticky',
            '.page-head{display:flex',
            '.card,.panel{background:var(--surface)',
            '.section-title{display:flex',
            'label.field{display:grid',
            '.task-progress{display:flex',
            '.status-spinner{width:1rem',
            '.page-load-action{display:flex',
            '.button.secondary{border-color:var(--accent);background:var(--accent);color:#fff}',
            'button:disabled{cursor:not-allowed;border-color:#d3dde1;',
            '.metric{border:1px solid var(--line);border-radius:14px;padding:18px;'
            'background:var(--surface);min-width:0;text-align:center}',
            '.state-row,.diag-row{border-top:1px solid var(--line);padding:7px 0;'
            'min-width:0;text-align:center}',
            '.published-tile{border:1px solid var(--line);border-radius:9px;'
            'padding:9px 10px;background:var(--soft);min-width:0;text-align:center}',
            '.setup-main button,.setup-main .button{width:100%}',
            '.setup-main .section-title button.compact{width:auto;',
            'input[aria-invalid="true"],select[aria-invalid="true"],textarea[aria-invalid="true"]',
        ):
            self.assertIn(rule, setup_wizard.portal_ui.PORTAL_CSS)
            self.assertIn(rule, web_portal_ui.PORTAL_CSS)
        self.assertIn('document.addEventListener("invalid"', setup_wizard.portal_ui.PORTAL_JS)
        self.assertIn('document.addEventListener("invalid"', web_portal_ui.PORTAL_JS)

    def test_wifi_scan_deduplicates_and_orders_visible_networks(self):
        class Station:
            def active(self, value):
                self.enabled = value

            def scan(self):
                return (
                    (b'Weak', b'', 1, -80, 3, False),
                    (b'Strong', b'', 6, -40, 3, False),
                    (b'Weak', b'', 11, -60, 3, False),
                    (b'', b'', 1, -20, 3, True),
                )

        class WLAN:
            IF_STA = 0

            def __new__(cls, interface):
                return Station()

        fake_network = type('Network', (), {'WLAN': WLAN, 'STA_IF': 0})
        with mock.patch.object(wifi_recovery, 'network', fake_network):
            networks = wifi_recovery.scan_wifi_networks()
        self.assertEqual(networks, [
            {'ssid': 'Strong', 'rssi': -40},
            {'ssid': 'Weak', 'rssi': -60},
        ])

    def test_wifi_scan_route_returns_cache_while_refresh_runs_in_background(self):
        async def scenario():
            wifi_recovery._wifi_scan_cache = []
            wifi_recovery._wifi_scan_updated_ms = None
            wifi_recovery._wifi_scan_task = None
            with mock.patch.object(
                wifi_recovery, 'scan_wifi_networks',
                return_value=[{'ssid': 'Cached', 'rssi': -45}]
            ):
                self.assertEqual(wifi_recovery.cached_wifi_networks(), [])
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                self.assertEqual(
                    wifi_recovery.cached_wifi_networks(refresh=False),
                    [{'ssid': 'Cached', 'rssi': -45}],
                )

        asyncio.run(scenario())

    def test_configuration_keeps_login_passwords_as_verifiers(self):
        config = credential_store.build_configuration(
            self.fields(), 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        credential_store.save(config)
        stored = b''.join(
            value for key, value in credential_store._memory_values.items()
            if key.startswith('cfg') and isinstance(value, bytes)
        )

        self.assertNotIn(b'Portal-Cedar-47!River', stored)
        self.assertNotIn(b'Console-Ash-82!Stone', stored)
        self.assertIn(b'mqtt-secret', stored)
        self.assertTrue(credential_security.verify_password(
            'Portal-Cedar-47!River', credential_store.load()['portal']['password_verifier']
        ))

    def test_setup_is_incomplete_until_signed_application_is_staged(self):
        config = credential_store.build_configuration(
            self.fields(), 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        credential_store.save(config)
        self.assertFalse(credential_store.is_provisioned())

        credential_store.mark_provisioned(config)
        self.assertTrue(credential_store.is_provisioned())


    def test_setup_rejects_reused_or_mismatched_passwords(self):
        params = self.fields()
        params.update({
            'portal_password': 'Same-Cedar-47!River',
            'portal_password_confirm': 'Same-Cedar-47!River',
            'recovery_password': 'Same-Cedar-47!River',
            'recovery_password_confirm': 'Same-Cedar-47!River',
            'install_mode': 'upload',
            'mqtt_ssl': '1',
        })
        with self.assertRaisesRegex(ValueError, 'must all differ'):
            setup_wizard._form_values(params)

        params['recovery_password'] = 'Different-Ash-82!Stone'
        with self.assertRaisesRegex(ValueError, 'do not match'):
            setup_wizard._form_values(params)

    def test_first_boot_page_collects_only_bootstrap_credentials(self):
        html = setup_wizard._page('csrf-token')
        self.assertIn('<header class="topbar setup-topbar">', html)
        self.assertLess(html.index('<header class="topbar setup-topbar">'), html.index('<main class="setup-main">'))
        self.assertLess(html.index('<main class="setup-main">'), html.index('<div class="setup-steps"'))
        self.assertGreater(html.index('<div class="setup-steps"'), html.index('</header>'))
        self.assertIn('.setup-main{width:auto;max-width:none;', setup_wizard.portal_ui.PORTAL_CSS)
        self.assertIn('id="device-name"', html)
        self.assertIn('id="mdns-hostname"', html)
        self.assertIn('id="wifi-network-select"', html)
        self.assertIn('id="wifi-manual-field"', html)
        self.assertIn('Enter network name manually', html)
        self.assertIn('fetch("/wifi-networks"', html)
        self.assertIn('hostnameFromDevice()', html)
        self.assertIn('mdnsEdited=true', html)
        self.assertIn('<div class="credential-pair">', html)
        self.assertLess(html.index('Portal password'), html.index('Confirm portal password'))
        self.assertLess(html.index('Recovery AP password'), html.index('Confirm recovery AP password'))
        self.assertLess(html.index('Recovery console password'), html.index('Confirm recovery console password'))
        self.assertIn('Recovery console password', html)
        self.assertIn('Confirm recovery console password', html)
        self.assertNotIn('Confirm recovery password', html)
        for name in (
            'device_name', 'wifi_ssid', 'wifi_password',
            'wifi_dhcp', 'wifi_ip_address', 'wifi_subnet_mask',
            'wifi_gateway', 'wifi_dns_server',
            'certificate_hostname', 'browser_time',
            'portal_password',
            'recovery_ap_password', 'recovery_password'
        ):
            self.assertIn('name="' + name + '"', html)
        self.assertIn('name="recovery_ap_password_confirm"', html)
        self.assertIn('name="portal_transport"', html)
        self.assertNotIn('name="profile"', html)
        self.assertNotIn('name="mqtt_server"', html)
        self.assertNotIn('name="mqtt_password"', html)
        self.assertNotIn('value="download"', html)
        self.assertIn('value="upload"', html)
        self.assertIn('new Date().toISOString()', html)
        self.assertIn('name="wifi_dhcp" type="checkbox" ', html)
        self.assertIn('value="true" checked', html)
        self.assertIn('Use DHCP to obtain network settings automatically', html)
        self.assertIn('Default gateway', html)
        self.assertIn('id="wifi-static-settings" class="grid" hidden', html)
        self.assertIn('syncNetworkMode()', html)
        original_preloaded = setup_wizard_views._preloaded_application_available
        setup_wizard_views._preloaded_application_available = lambda: True
        try:
            preloaded = setup_wizard._page('csrf-token')
        finally:
            setup_wizard_views._preloaded_application_available = original_preloaded
        self.assertIn('class="badge good tooltip-badge"', preloaded)
        self.assertIn('>Application ready</span>', preloaded)
        self.assertIn('data-tooltip="The factory-installed signed application is ready.', preloaded)
        self.assertNotIn('<p class="notice">The factory-installed signed application', preloaded)
        self.assertIn(
            'href="/assets/portal.css?v=' + setup_wizard.SETUP_ASSET_VERSION + '"',
            preloaded,
        )
        self.assertIn('<section class="card"><div class="section-title">', preloaded)
        self.assertIn('class="field">Portal password', preloaded)
        self.assertIn('.setup-application-status{display:flex;', setup_wizard.portal_ui.PORTAL_CSS)
        self.assertIn('margin-left:auto', setup_wizard.portal_ui.PORTAL_CSS)
        self.assertIn('top:calc(100% + 8px);right:0', setup_wizard.portal_ui.PORTAL_CSS)
        self.assertGreater(
            preloaded.index('class="setup-application-status"'),
            preloaded.index('<h2>Device &amp; Application</h2>')
        )
        device_section_end = preloaded.index(
            '</section>', preloaded.index('<h2>Device &amp; Application</h2>')
        )
        self.assertLess(preloaded.index('class="setup-application-status"'), device_section_end)
        certificates = setup_wizard._certificate_page('csrf-token', 'whes01.local')
        self.assertIn('id="trust-ca"', certificates)
        self.assertNotIn('id="mqtt-ca"', certificates)
        self.assertNotIn('id="update-ca"', certificates)
        self.assertIn('id="portal-cert"', certificates)
        self.assertIn('id="portal-key"', certificates)
        self.assertIn('id="acme-directory"', certificates)
        self.assertIn('id="certificate-hostname"', certificates)
        self.assertIn('value="whes01.local" readonly', certificates)
        self.assertIn('<code>.local</code> hostname with mDNS', certificates)
        self.assertIn('action="/enroll-certificate"', certificates)
        self.assertIn('action="/manual-certificates"', certificates)
        self.assertIn('enctype="multipart/form-data"', certificates)
        self.assertNotIn('onclick=', certificates)
        self.assertIn('id="continue" class="secondary" disabled', certificates)
        self.assertIn('name="certificate_mode" value="self_signed"', certificates)
        self.assertIn('Continue with self-signed certificate', certificates)
        enrolling = setup_wizard._enrollment_page('Creating the certificate order')
        self.assertIn('Creating the certificate order', enrolling)
        self.assertIn('url=/enrollment-status', enrolling)
        self.assertIn('Check status now', enrolling)
        complete = setup_wizard._certificate_complete_page(
            'csrf-token', 'Certificate enrolled until tomorrow', 'acme'
        )
        self.assertIn('class="status-spinner"', complete)
        self.assertNotIn('<progress', complete)
        self.assertIn('Certificate enrolled until tomorrow', complete)
        self.assertIn('action="/install" method="post"', complete)
        self.assertIn('name="csrf" value="csrf-token"', complete)
        self.assertIn('name="certificate_mode" value="acme"', complete)
        self.assertIn('document.getElementById("next-step").submit()', complete)
        self.assertNotIn('Automatic enrollment', complete)
        ready = setup_wizard._certificate_page(
            'csrf-token', 'whes01.local', 'Certificate enrolled', ready=True
        )
        self.assertIn('Certificate enrolled', ready)
        self.assertIn('id="continue" class="secondary">', ready)
        self_signed = setup_wizard._certificate_resume_page('csrf-token', {
            'certificate': {'hostname': 'whes01.local', 'mode': 'self_signed'},
        })
        self.assertIn('>Self-signed ready</span>', self_signed)
        self.assertIn(
            'data-tooltip="' + setup_wizard.SELF_SIGNED_READY_MESSAGE + '"',
            self_signed,
        )
        self.assertNotIn(
            '<p class="notice" role="status">' +
            setup_wizard.SELF_SIGNED_READY_MESSAGE,
            self_signed,
        )
        self.assertLess(
            self_signed.index('<h1>Install device certificates</h1>'),
            self_signed.index('>Self-signed ready</span>'),
        )
        handover = setup_wizard._handover_page('whes01.local', 'csrf-token')
        self.assertIn('http://whes01.local/resume/csrf-token', handover)
        self.assertIn('setup access point will now close', handover)
        source = Path(setup_wizard.__file__).read_text()
        resume_start = source.index("path == '/resume/' + session")
        resume_end = source.index('elif not authenticated:', resume_start)
        resume_route = source[resume_start:resume_end]
        self.assertIn("'200 OK', _certificate_resume_page", resume_route)
        self.assertNotIn("'Location', '/certificates'", resume_route)
        portal = setup_wizard._portal_handoff_page({
            'portal': {'transport': 'https'},
            'certificate': {'hostname': 'whes01.local'},
        }, 'Restarting')
        self.assertIn('https://whes01.local:8443/', portal)
        self.assertIn('window.location.replace(target)', portal)

    def test_certificate_completion_must_match_verified_installed_mode(self):
        original_validate = setup_workflow._validate_certificates
        original_details = setup_wizard.certificate_manager.certificate_details
        validation = []

        def validate(require_trust=True, **_kwargs):
            validation.append(require_trust)
            return True

        def details(path):
            if path == setup_wizard.CERTIFICATE_PATHS['portal-cert']:
                return {
                    'installed': True, 'subject': 'CN=whes01.local',
                    'issuer': 'CN=Home IoT CA',
                }
            return {'installed': True, 'subject': 'CN=Home IoT CA', 'issuer': 'CN=Home IoT CA'}

        setup_workflow._validate_certificates = validate
        setup_wizard.certificate_manager.certificate_details = details
        config = {'certificate': {'mode': 'acme'}}
        try:
            self.assertTrue(setup_wizard._validate_certificate_selection(config, 'acme'))
            self.assertEqual(validation, [True])
            with self.assertRaisesRegex(ValueError, 'certificate setup changed'):
                setup_wizard._validate_certificate_selection(config, 'self_signed')
            setup_wizard.certificate_manager.certificate_details = lambda _path: {
                'installed': True, 'subject': 'CN=whes01.local', 'issuer': 'CN=whes01.local'
            }
            with self.assertRaisesRegex(ValueError, 'self-issued'):
                setup_wizard._validate_certificate_files('acme')
        finally:
            setup_workflow._validate_certificates = original_validate
            setup_wizard.certificate_manager.certificate_details = original_details

    def test_certificate_resume_uses_persisted_acme_mode(self):
        original = setup_wizard_views._validate_certificate_selection
        setup_wizard_views._validate_certificate_selection = lambda _config, mode: mode == 'acme'
        try:
            html = setup_wizard._certificate_resume_page('csrf-token', {
                'certificate': {'mode': 'acme', 'hostname': 'whes01.local'},
            })
        finally:
            setup_wizard_views._validate_certificate_selection = original
        self.assertIn('ACME certificate files are installed and validated.', html)
        self.assertIn('name="certificate_mode" value="acme"', html)
        self.assertNotIn('Continue with self-signed certificate', html)

    def test_recovery_ap_password_must_be_confirmed(self):
        params = self.fields()
        params.update({
            'portal_password': 'Portal-Cedar-47!River',
            'portal_password_confirm': 'Portal-Cedar-47!River',
            'recovery_password': 'Console-Ash-82!Stone',
            'recovery_password_confirm': 'Console-Ash-82!Stone',
            'recovery_ap_password_confirm': 'Different-Access-Cedar-47!',
        })
        with self.assertRaisesRegex(ValueError, 'recovery AP passwords do not match'):
            setup_wizard._form_values(params)

    def test_portal_transport_defaults_to_https_when_certificate_is_present(self):
        original = setup_wizard_views._file_exists
        setup_wizard_views._file_exists = lambda _path: True
        try:
            config = {
                'portal': {'transport': 'auto'},
                'certificate': {'hostname': 'whes01.local'},
            }
            self.assertEqual(
                setup_wizard._portal_url(config),
                'https://whes01.local:8443/',
            )
            config['portal']['transport'] = 'http'
            self.assertEqual(
                setup_wizard._portal_url(config),
                'http://whes01.local:8080/',
            )
        finally:
            setup_wizard_views._file_exists = original

    def test_setup_selects_self_signed_fallback_and_auto_transport(self):
        params = self.fields()
        params.update({
            'portal_password': 'Portal-Cedar-47!River',
            'portal_password_confirm': 'Portal-Cedar-47!River',
            'recovery_password': 'Console-Ash-82!Stone',
            'recovery_password_confirm': 'Console-Ash-82!Stone',
        })
        values = setup_wizard._form_values(params)
        self.assertEqual(values['certificate_mode'], 'self_signed')
        self.assertEqual(values['portal_transport'], 'auto')

    def test_network_configuration_defaults_to_dhcp_for_existing_values(self):
        config = credential_store.build_configuration(
            self.fields(), 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        self.assertTrue(config['wifi']['dhcp'])
        self.assertEqual(config['wifi']['gateway'], '')

        credential_store.mark_provisioned(config)
        settings = credential_store.public_settings()
        self.assertTrue(settings['wifi_dhcp'])
        self.assertEqual(settings['wifi_gateway'], '')

    def test_device_api_defaults_disabled_and_requires_a_separate_port(self):
        config = credential_store.build_configuration(
            self.fields(), 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        self.assertEqual(config['api'], {
            'enabled': False, 'port': 8444, 'auth': 'mtls'
        })
        credential_store.mark_provisioned(config)
        credential_store.update_operational_settings({
            'api_enabled': True, 'api_port': 9444
        })
        self.assertTrue(credential_store.public_settings()['api_enabled'])
        self.assertEqual(credential_store.public_settings()['api_port'], 9444)

        with self.assertRaisesRegex(ValueError, 'differ from the portal port'):
            credential_store.update_operational_settings({
                'portal_port': 9444
            })

    def test_schema_four_credentials_migrate_with_api_disabled(self):
        config = credential_store.build_configuration(
            self.fields(), 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        config['schema'] = 4
        config.pop('api')
        store = credential_store._nvs()
        store.set_blob('cfg0', json.dumps(config).encode())
        store.set_i32('active', 0)
        store.commit()

        migrated = credential_store.load()

        self.assertEqual(migrated['schema'], credential_store.SCHEMA_VERSION)
        self.assertFalse(migrated['api']['enabled'])
        self.assertEqual(migrated['api']['auth'], 'mtls')

    def test_static_network_configuration_includes_default_gateway(self):
        values = self.fields()
        values.update({
            'wifi_dhcp': False,
            'wifi_ip_address': '192.168.50.24',
            'wifi_subnet_mask': '255.255.255.0',
            'wifi_gateway': '192.168.50.1',
            'wifi_dns_server': '1.1.1.1',
        })
        config = credential_store.build_configuration(
            values, 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        self.assertFalse(config['wifi']['dhcp'])
        self.assertEqual(config['wifi']['gateway'], '192.168.50.1')

        credential_store.mark_provisioned(config)
        settings = credential_store.public_settings()
        self.assertFalse(settings['wifi_dhcp'])
        self.assertEqual(settings['wifi_ip_address'], '192.168.50.24')
        self.assertEqual(settings['wifi_subnet_mask'], '255.255.255.0')
        self.assertEqual(settings['wifi_gateway'], '192.168.50.1')
        self.assertEqual(settings['wifi_dns_server'], '1.1.1.1')

    def test_static_network_rejects_missing_or_wrong_gateway(self):
        values = self.fields()
        values.update({
            'wifi_dhcp': False,
            'wifi_ip_address': '192.168.50.24',
            'wifi_subnet_mask': '255.255.255.0',
            'wifi_gateway': '',
            'wifi_dns_server': '1.1.1.1',
        })
        with self.assertRaisesRegex(ValueError, 'default gateway'):
            credential_store.build_configuration(
                values, 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
            )

        values['wifi_gateway'] = '192.168.51.1'
        with self.assertRaisesRegex(ValueError, 'same subnet'):
            credential_store.build_configuration(
                values, 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
            )

    def test_station_receives_dhcp_or_static_network_configuration(self):
        class Station:
            def __init__(self):
                self.calls = []

            def active(self, value):
                self.calls.append(('active', value))

            def ipconfig(self, **values):
                self.calls.append(('ipconfig', values))

            def ifconfig(self, value):
                self.calls.append(('ifconfig', value))

        station = Station()
        credential_store.configure_station(station, {'dhcp': True})
        self.assertEqual(station.calls, [
            ('active', True), ('ipconfig', {'dhcp4': True})
        ])

        station = Station()
        credential_store.configure_station(station, {
            'dhcp': False,
            'ip_address': '10.20.30.40',
            'subnet_mask': '255.255.255.0',
            'gateway': '10.20.30.1',
            'dns_server': '9.9.9.9',
        })
        self.assertEqual(station.calls, [
            ('active', True),
            ('ifconfig', ('10.20.30.40', '255.255.255.0', '10.20.30.1', '9.9.9.9')),
        ])

    def test_browser_utc_bootstraps_rtc_without_ntp(self):
        calls = []

        class RTC:
            def datetime(self, value):
                calls.append(value)

        class Machine:
            @staticmethod
            def RTC():
                return RTC()

        original = setup_workflow.machine
        setup_workflow.machine = Machine
        try:
            self.assertEqual(
                setup_wizard._set_rtc_from_browser_time('2026-07-23T05:32:40.123Z'),
                (2026, 7, 23, 5, 32, 40)
            )
            self.assertEqual(calls, [(2026, 7, 23, 0, 5, 32, 40, 0)])
            with self.assertRaisesRegex(ValueError, 'outside the supported range'):
                setup_wizard._set_rtc_from_browser_time('2001-01-01T00:00:00Z')
        finally:
            setup_workflow.machine = original

    def test_setup_requires_a_single_label_mdns_hostname(self):
        params = self.fields()
        params.update({
            'portal_password': 'Portal-Cedar-47!River',
            'portal_password_confirm': 'Portal-Cedar-47!River',
            'recovery_password': 'Console-Ash-82!Stone',
            'recovery_password_confirm': 'Console-Ash-82!Stone',
            'install_mode': 'upload',
            'certificate_hostname': 'whes01.home.arpa',
        })
        with self.assertRaisesRegex(ValueError, r'followed by \.local'):
            setup_wizard._form_values(params)
        params['certificate_hostname'] = 'WHES01.local.'
        self.assertEqual(
            setup_wizard._form_values(params)['certificate_hostname'],
            'whes01.local'
        )

    def test_certificate_multipart_form_preserves_binary_files(self):
        boundary = 'browser-boundary-123'
        certificate = b'\x30\x82\x00\xffcertificate'
        body = (
            b'--' + boundary.encode() + b'\r\n'
            b'Content-Disposition: form-data; name="csrf"\r\n\r\n'
            b'csrf-token\r\n--' + boundary.encode() + b'\r\n'
            b'Content-Disposition: form-data; name="trust_ca"; filename="root.der"\r\n'
            b'Content-Type: application/pkix-cert\r\n\r\n' + certificate +
            b'\r\n--' + boundary.encode() + b'--\r\n'
        )
        values = setup_wizard._multipart_form(
            body, 'multipart/form-data; boundary=' + boundary
        )
        self.assertEqual(values['csrf'], b'csrf-token')
        self.assertEqual(values['trust_ca'], certificate)

    def test_mqtt_tls_cannot_be_disabled(self):
        values = self.fields()
        values['mqtt_ssl'] = False
        with self.assertRaisesRegex(ValueError, 'TLS is mandatory'):
            credential_store.build_configuration(
                values, 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
            )

    def test_mqtt_can_be_configured_after_first_boot(self):
        values = self.fields()
        values.update({'mqtt_server': '', 'mqtt_port': 8883, 'mqtt_ssl': True})
        config = credential_store.build_configuration(
            values, 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        credential_store.mark_provisioned(config)
        self.assertFalse(credential_store.public_settings()['mqtt_configured'])

        credential_store.update_operational_settings({
            'mqtt_server': 'mqtt.home.arpa', 'mqtt_port': 8883,
            'mqtt_username': 'device-user', 'mqtt_password': 'broker-secret'
        })
        loaded = credential_store.load(require_provisioned=True)
        self.assertTrue(loaded['mqtt']['configured'])
        self.assertEqual(loaded['mqtt']['password'], 'broker-secret')
        self.assertNotIn('mqtt_password', credential_store.public_settings())

        credential_store.update_operational_settings({
            'wifi_ssid': 'replacement-network',
            'mqtt_username': 'replacement-user',
        })
        loaded = credential_store.load(require_provisioned=True)
        self.assertEqual(loaded['wifi']['password'], 'wifi-password')
        self.assertEqual(loaded['mqtt']['password'], 'broker-secret')

        with self.assertRaisesRegex(ValueError, 'release channel'):
            credential_store.update_operational_settings({
                'release_channel': 'untrusted'
            })
        self.assertEqual(
            credential_store.load(require_provisioned=True)['release']['channel'],
            'stable'
        )

    def test_portal_port_is_optional_persisted_and_reserves_enrollment_port(self):
        config = credential_store.build_configuration(
            self.fields(), 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        credential_store.mark_provisioned(config)
        self.assertEqual(credential_store.public_settings()['portal_port'], 8443)
        self.assertEqual(
            credential_store.public_settings()['portal_session_timeout_s'], 3600
        )
        self.assertIsNone(
            credential_store.load(require_provisioned=True)['portal']['port']
        )

        credential_store.update_operational_settings({'portal_port': '9443'})
        self.assertEqual(
            credential_store.public_settings()['portal_port'], 9443
        )
        with self.assertRaisesRegex(ValueError, 'reserved port 80'):
            credential_store.update_operational_settings({'portal_port': '80'})
        self.assertEqual(
            credential_store.public_settings()['portal_port'], 9443
        )

    def test_user_time_logging_timeout_and_syslog_settings_are_bounded(self):
        config = credential_store.build_configuration(
            self.fields(), 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        credential_store.mark_provisioned(config)

        credential_store.update_operational_settings({
            'timezone_offset_minutes': 60,
            'timezone_name': 'Europe/London',
            'log_buffer_lines': 300,
            'portal_session_timeout_s': 1800,
            'syslog_enabled': True,
            'syslog_host': 'logs.local',
            'syslog_port': 6514,
            'syslog_transport': 'tls',
            'release_check_schedule': 'weekly',
            'release_check_time': '04:30',
            'release_check_weekday': 6,
            'certificate_mode': 'acme',
            'acme_directory_url': 'https://acme.example/directory',
            'certificate_hostname': 'controller.local',
        })
        public = credential_store.public_settings()
        self.assertEqual(public['timezone_offset_minutes'], 60)
        self.assertEqual(public['timezone_name'], 'Europe/London')
        self.assertEqual(public['log_buffer_lines'], 300)
        self.assertEqual(public['portal_session_timeout_s'], 1800)
        self.assertEqual(public['syslog_transport'], 'tls')
        self.assertEqual(public['release_check_schedule'], 'weekly')
        self.assertEqual(public['release_check_time'], '04:30')
        self.assertEqual(public['release_check_weekday'], 6)
        self.assertEqual(public['certificate_mode'], 'acme')
        self.assertEqual(
            public['acme_directory_url'], 'https://acme.example/directory'
        )
        self.assertEqual(public['certificate_hostname'], 'controller.local')

        with self.assertRaisesRegex(ValueError, 'log entry limit'):
            credential_store.update_operational_settings({'log_buffer_lines': 501})
        with self.assertRaisesRegex(ValueError, 'portal timeout'):
            credential_store.update_operational_settings({'portal_session_timeout_s': 299})
        with self.assertRaisesRegex(ValueError, 'time-zone offset'):
            credential_store.update_operational_settings({'timezone_offset_minutes': 900})
        with self.assertRaisesRegex(ValueError, 'update check schedule'):
            credential_store.update_operational_settings({'release_check_schedule': 'monthly'})
        with self.assertRaisesRegex(ValueError, 'update check time'):
            credential_store.update_operational_settings({'release_check_time': '25:00'})

    def test_schema_five_implicit_timeout_migrates_to_sixty_minutes(self):
        config = credential_store.build_configuration(
            self.fields(), 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        config['schema'] = 5
        config['portal']['session_timeout_s'] = 28800
        credential_store.save(credential_store._migrate_v5(config))

        loaded = credential_store.load(require_provisioned=False)
        self.assertEqual(loaded['schema'], credential_store.SCHEMA_VERSION)
        self.assertEqual(loaded['portal']['session_timeout_s'], 3600)

    def test_network_trial_confirms_candidate_after_authenticated_reconnect(self):
        config = credential_store.build_configuration(
            self.fields(), 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        credential_store.mark_provisioned(config)

        result = credential_store.update_operational_settings({
            'wifi_ssid': 'replacement-network',
            'wifi_password': 'replacement-password',
        }, network_trial=True)
        self.assertTrue(result['network_trial_pending'])
        self.assertEqual(credential_store.prepare_network_trial_boot(), 'trial')
        self.assertTrue(credential_store.confirm_network_trial())
        self.assertFalse(credential_store.network_trial_pending())
        self.assertEqual(
            credential_store.load(require_provisioned=True)['wifi']['ssid'],
            'replacement-network'
        )

    def test_unconfirmed_network_trial_rolls_back_on_next_boot(self):
        config = credential_store.build_configuration(
            self.fields(), 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        credential_store.mark_provisioned(config)
        credential_store.update_operational_settings({
            'wifi_dhcp': False,
            'wifi_ip_address': '192.168.1.42',
            'wifi_subnet_mask': '255.255.255.0',
            'wifi_gateway': '192.168.1.1',
            'wifi_dns_server': '192.168.1.1',
        }, network_trial=True)

        self.assertEqual(credential_store.prepare_network_trial_boot(), 'trial')
        self.assertEqual(
            credential_store.prepare_network_trial_boot(), 'rolled_back'
        )
        restored = credential_store.load(require_provisioned=True)
        self.assertTrue(restored['wifi']['dhcp'])
        self.assertEqual(restored['wifi']['ssid'], 'home-network')
        self.assertFalse(credential_store.network_trial_pending())

    def test_static_gateway_cannot_equal_device_address(self):
        config = credential_store.build_configuration(
            self.fields(), 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        credential_store.mark_provisioned(config)
        with self.assertRaisesRegex(ValueError, 'gateway cannot be the device IP'):
            credential_store.update_operational_settings({
                'wifi_dhcp': False,
                'wifi_ip_address': '192.168.1.42',
                'wifi_subnet_mask': '255.255.255.0',
                'wifi_gateway': '192.168.1.42',
                'wifi_dns_server': '192.168.1.1',
            }, network_trial=True)

    def test_factory_bootstrap_key_is_separate_and_erasable(self):
        store = credential_store._nvs()
        store.set_blob('bootkey', b'unique-factory-setup-password')
        store.set_blob('verifykey', bytes(range(64)))
        store.commit()
        self.assertEqual(
            credential_store.bootstrap_key(), 'unique-factory-setup-password'
        )
        credential_store.erase_bootstrap_key()
        self.assertEqual(credential_store.bootstrap_key(), '')
        self.assertEqual(credential_store.update_verification_key(), bytes(range(64)))

    def test_factory_reset_preserves_trust_key_and_arms_first_boot(self):
        config = credential_store.build_configuration(
            self.fields(), 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        credential_store.mark_provisioned(config)
        store = credential_store._nvs()
        store.set_blob('verifykey', bytes(range(64)))
        store.commit()

        credential_store.request_factory_reset('Setup-Maple-53!Harbour')
        self.assertTrue(credential_store.factory_reset_pending())
        self.assertTrue(credential_store.is_provisioned())
        self.assertEqual(
            credential_store.bootstrap_key(), 'Setup-Maple-53!Harbour'
        )

        credential_store.complete_factory_reset()
        self.assertFalse(credential_store.factory_reset_pending())
        self.assertFalse(credential_store.is_provisioned())
        self.assertEqual(
            credential_store.update_verification_key(), bytes(range(64))
        )

    def test_factory_reset_rejects_weak_or_oversized_setup_password(self):
        with self.assertRaisesRegex(ValueError, 'at least 16'):
            credential_store.request_factory_reset('short')
        with self.assertRaisesRegex(ValueError, 'must not exceed 63'):
            credential_store.request_factory_reset(
                'Ab9!' + ('varied-passphrase-' * 5)
            )

    def test_configuration_has_no_application_profile(self):
        config = credential_store.build_configuration(
            self.fields(), 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        self.assertNotIn('profile', config['release'])

    def test_first_boot_selects_optional_module_settings(self):
        original = setup_wizard.app_update.configure_pending_update
        selections = []
        setup_wizard.app_update.configure_pending_update = (
            lambda value: selections.append(value) or {'status': 'ready'}
        )
        try:
            result = setup_wizard._prepare_setup_application({
                'optional_groups': ['module_settings'],
            })
        finally:
            setup_wizard.app_update.configure_pending_update = original
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(selections, [{'module_settings': True}])

    def test_first_boot_allows_missing_module_settings(self):
        original = setup_wizard.app_update.configure_pending_update
        selections = []
        setup_wizard.app_update.configure_pending_update = (
            lambda value: selections.append(value) or {'status': 'ready'}
        )
        try:
            result = setup_wizard._prepare_setup_application({
                'optional_groups': [],
            })
        finally:
            setup_wizard.app_update.configure_pending_update = original
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(selections, [{'module_settings': False}])


if __name__ == '__main__':
    unittest.main()
