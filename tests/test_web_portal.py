import unittest
import asyncio
import builtins
import os
import tempfile
from pathlib import Path
from unittest import mock

import web_portal
import portal_http
from portal_contracts import PortalDependencies
import credential_security
import http_support
import web_portal_ui as portal_ui
from tools.check_micropython_compat import compatibility_errors
from web_portal import (
    apply_loglevel_change,
    apply_logging_change,
    apply_portal_action,
    constant_time_equal,
    credentials_match,
    credentials_match_async,
    configuration_backup_filename,
    download_response,
    friendly_label,
    has_portal_session,
    is_client_disconnect_error,
    make_tls_context,
    parse_request_line,
    redirect,
    render_login_page,
    render_settings_page,
    render_log_text,
    render_logs_html,
    render_page,
    render_page_parts,
    requested_loglevel,
    url_decode,
    response,
    write_buffered_response,
)


class WebPortalTests(unittest.TestCase):
    def test_new_operations_pages_expose_runtime_controls(self):
        settings = {
            'portal_transport': 'auto',
            'portal_port': 8443,
            'portal_session_timeout_s': 3600,
            'ntp_servers': ('pool.ntp.org',),
            'timezone_offset_minutes': 60,
            'timezone_name': 'Europe/London',
            'log_buffer_lines': 250,
            'syslog_enabled': True,
            'syslog_host': 'logs.local',
            'syslog_port': 6514,
            'syslog_transport': 'tls',
        }
        portal = web_portal.render_portal_settings_page('csrf', settings)
        ntp = web_portal.render_ntp_settings_page('csrf', settings)
        logging = web_portal.render_logging_settings_page('csrf', settings)
        backup = web_portal.render_configuration_backup_page('csrf')
        certificates = web_portal.render_certificate_page('csrf', certificates={
            'acme_settings': {
                'directory_url': 'https://ca.local/directory',
                'hostname': 'controller.local',
            }
        })

        self.assertIn('name="portal_session_timeout_minutes"', portal)
        self.assertIn('Inactive session timeout (minutes)', portal)
        self.assertIn('value="60"', portal)
        self.assertIn('value="8443"', portal)
        self.assertIn('name="timezone_name"', ntp)
        self.assertIn('value="Europe/London" selected', ntp)
        self.assertIn('Daylight-saving changes are applied automatically', ntp)
        self.assertIn('name="log_buffer_lines"', logging)
        self.assertIn('name="syslog_transport"', logging)
        self.assertLess(
            logging.index('name="syslog_transport"'),
            logging.index('name="syslog_port"')
        )
        self.assertIn('id="syslog-transport"', logging)
        self.assertIn('id="syslog-port"', logging)
        self.assertIn('this.value==="tls"?"6514":"514"', logging)
        self.assertIn('name="syslog_enabled"', logging)
        self.assertIn('name="syslog_audit_enabled"', logging)
        tls_default = web_portal.render_logging_settings_page(
            'csrf', {'syslog_transport': 'tls'}
        )
        self.assertIn('name="syslog_port" type="number"', tls_default)
        self.assertIn('required value="6514"', tls_default)
        self.assertIn('Encrypt backup and include secrets', backup)
        self.assertIn('id="export-encryption" class="conditional-fields" disabled', backup)
        self.assertIn('Uploading backup ', backup)
        self.assertIn('Validating configuration · "+percent+"% (estimated)', backup)
        self.assertIn('Validating configuration · 100%', backup)
        self.assertIn('x.timeout=180000', backup)
        self.assertIn('Configuration validation timed out after 3 minutes', backup)
        self.assertIn('id="configuration-preview-panel" hidden', backup)
        self.assertIn('diffRows=p.changes||[]', backup)
        self.assertIn('label.textContent="Preview ready"', backup)
        self.assertIn('actionButton.disabled=false', backup)
        self.assertEqual(backup.count('id="configuration-action"'), 1)
        self.assertNotIn('id="configuration-apply"', backup)
        self.assertNotIn('id="configuration-preview"', backup)
        self.assertIn('class="restore-grid"', backup)
        self.assertIn('row.className="restore-card "+state', backup)
        self.assertIn('pane("Current",before)', backup)
        self.assertIn('pane("Backup",after)', backup)
        self.assertIn('portalRequire(importPassword', backup)
        self.assertNotIn('Protected content', backup)
        self.assertIn('name="directory_url"', certificates)
        self.assertIn('multiple', certificates)
        self.assertIn('Math.round(p.loaded*100/p.total)+"%"', certificates)
        self.assertNotIn('href="/portal-settings">Portal settings</a>', certificates)
        self.assertNotIn('href="/device-api">Device API settings</a>', certificates)

    def test_configuration_backup_filenames_include_utc_timestamp(self):
        self.assertEqual(
            configuration_backup_filename(False, 0),
            'ha-device-configuration-19700101-000000Z.json'
        )
        self.assertEqual(
            configuration_backup_filename(True, 0),
            'ha-device-complete-19700101-000000Z.encrypted.json'
        )

    def test_portal_marks_required_and_custom_invalid_fields(self):
        backup = web_portal.render_configuration_backup_page('csrf')
        certificates = web_portal.render_certificate_page('csrf')
        update = web_portal.render_updates_page('csrf', {})

        self.assertIn('id="configuration-import-file" type="file"', backup)
        self.assertIn('accept="application/json,.json" required', backup)
        self.assertIn('portalInvalid(confirmField', backup)
        self.assertIn('portalRequire(primary', certificates)
        self.assertIn('secondary.disabled=!d[1]', certificates)
        self.assertIn('if(!d[1])secondary.value=""', certificates)
        self.assertIn('.field[hidden]{display:none}', portal_ui.PORTAL_CSS)
        self.assertIn('portalRequire(input', update)
        self.assertIn('input[aria-invalid="true"]', portal_ui.PORTAL_CSS)
        self.assertIn('document.addEventListener("invalid"', portal_ui.PORTAL_JS)

    def test_restart_page_waits_for_complete_login_assets(self):
        page = portal_ui.restart_page('/login')

        self.assertIn('failures>=2', page)
        self.assertIn('if(!ok)throw Error()', page)
        self.assertIn('offline?2000:500', page)
        self.assertIn('id=\\"login-form\\"', page)
        self.assertIn('probe(a,":root{")', page)
        self.assertIn('Portal ready — opening login…', page)
        self.assertIn('"reconnect="+Date.now()', page)
        self.assertIn('Date.now()-started>=6000', page)
        self.assertIn('restart_probe', page)

    def test_health_history_groups_protocols_formats_values_and_can_reset(self):
        page = web_portal.render_health_history_page('csrf', {
            'timezone_offset_minutes': 60,
            'health_history': {
                'counters': {
                    'boots': 1,
                    'mqtt_publish_drops': 2,
                    'mqtt_publish_failures': 3,
                    'api_requests': 4,
                },
                'observations': {
                    'last_update_result': {
                        'kind': 'application', 'result': 'confirmed',
                        'version': '2.0.0', 'time': 1787396400,
                    }
                },
                'events': [{
                    'time': 1787396400,
                    'kind': 'api_request',
                    'detail': 'GET /api/v1/device',
                }],
            }
        })

        self.assertIn('<h3>MQTT</h3>', page)
        self.assertIn('<h3>API</h3>', page)
        self.assertIn('<h3>Updates</h3>', page)
        self.assertIn('<time>', page)
        self.assertIn('<span>Type</span><strong>application</strong>', page)
        self.assertIn('<span>Result</span><strong>confirmed</strong>', page)
        self.assertIn('<span>Version</span><strong>2.0.0</strong>', page)
        self.assertIn('<span>Completed at</span><strong>', page)
        self.assertNotIn('last update result</span>', page)
        self.assertNotIn('&#x27;result&#x27;', page)
        self.assertIn('/reset-health-history', page)
        self.assertNotIn('href="/logging">Open device log</a>', page)

    def test_overview_shows_device_api_status(self):
        overview = web_portal.render_overview_status({'api': 'online'})
        self.assertIn('Device API', overview)
        self.assertIn('online', overview)
    def test_http_request_parser_rejects_oversized_and_ambiguous_headers(self):
        class Reader:
            def __init__(self, lines):
                self.data = b''.join(lines)

            async def readline(self):
                index = self.data.find(b'\n')
                if index < 0:
                    value, self.data = self.data, b''
                    return value
                value, self.data = self.data[:index + 1], self.data[index + 1:]
                return value

            async def read(self, size):
                value, self.data = self.data[:size], self.data[size:]
                return value

        with self.assertRaisesRegex(ValueError, 'line exceeds'):
            asyncio.run(http_support.read_request(Reader((
                b'G' * (http_support.MAX_REQUEST_LINE_BYTES + 1),
            ))))
        with self.assertRaisesRegex(ValueError, 'duplicate security-sensitive'):
            asyncio.run(http_support.read_request(Reader((
                b'POST / HTTP/1.1\r\n',
                b'Content-Length: 1\r\n',
                b'Content-Length: 2\r\n',
                b'\r\n',
            ))))

    def test_buffered_request_reader_preserves_body_and_next_request(self):
        class Reader:
            def __init__(self, data):
                self.data = data
                self.reads = 0

            async def read(self, size):
                self.reads += 1
                value, self.data = self.data[:size], self.data[size:]
                return value

        source = Reader(
            b'POST /first HTTP/1.1\r\nContent-Length: 4\r\n\r\nbody'
            b'GET /second HTTP/1.1\r\nConnection: close\r\n\r\n'
        )

        async def parse():
            reader = http_support.buffered(source)
            first, headers = await http_support.read_request(reader)
            body = await http_support.read_exact_body(reader, 4, 4)
            second, _headers = await http_support.read_request(reader)
            return first, headers, body, second

        first, headers, body, second = asyncio.run(parse())
        self.assertEqual(first, b'POST /first HTTP/1.1\r\n')
        self.assertEqual(headers['content-length'], '4')
        self.assertEqual(body, b'body')
        self.assertEqual(second, b'GET /second HTTP/1.1\r\n')
        self.assertEqual(source.reads, 1)

    def test_audit_peer_address_uses_stream_metadata(self):
        class Stream:
            def get_extra_info(self, key):
                return ('192.0.2.44', 55231) if key == 'peername' else None

        self.assertEqual(
            web_portal.request_peer_address(Stream()), '192.0.2.44'
        )

    def test_http_reader_optimisations_are_optional_on_an_older_core(self):
        reader = object()
        timeout = TimeoutError()

        with (
            mock.patch.object(http_support, 'BUFFERED_READER_API', 0),
            mock.patch.object(http_support, 'buffered') as buffered,
        ):
            self.assertIs(portal_http.compatible_http_reader(reader), reader)
            buffered.assert_not_called()
        with mock.patch.object(http_support, 'is_timeout_error', None):
            self.assertTrue(portal_http.is_http_timeout_error(timeout))

    def test_compatibility_gate_rejects_slice_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'bad_buffer.py'
            source.write_text('value = bytearray()\ndel value[:1]\n')
            errors = compatibility_errors(source)

        self.assertTrue(any('slice deletion' in error for error in errors))

    def test_request_line_parsing(self):
        self.assertEqual(
            parse_request_line('GET /?view=all HTTP/1.1'),
            ('GET', '/?view=all')
        )

    def test_password_authentication(self):
        verifier = credential_security.password_verifier(
            'Secret-Cedar-47!River', bytes(range(16))
        )
        self.assertTrue(constant_time_equal('same', 'same'))
        self.assertFalse(constant_time_equal('same', 'different'))
        self.assertTrue(credentials_match('admin', 'Secret-Cedar-47!River', 'admin', verifier))
        self.assertFalse(credentials_match('admin', 'wrong', 'admin', verifier))
        self.assertFalse(credentials_match('other', 'Secret-Cedar-47!River', 'admin', verifier))
        self.assertTrue(has_portal_session({'cookie': 'a=1; ham_session=session'}, 'session'))
        self.assertFalse(has_portal_session({'cookie': 'ham_session=wrong'}, 'session'))
        self.assertEqual(url_decode('%7B%22name%22%3A+%22test%22%7D'), '{"name": "test"}')
        self.assertEqual(url_decode('%C2%B0C'), '°C')
        self.assertTrue(asyncio.run(credentials_match_async(
            'admin', 'Secret-Cedar-47!River', 'admin', verifier
        )))
        self.assertFalse(asyncio.run(credentials_match_async(
            'admin', 'wrong', 'admin', verifier
        )))

    def test_login_page_uses_post_and_password_field(self):
        html = render_login_page('portal-admin', 'Invalid username or password.')

        self.assertIn('action="/login" method="post"', html)
        self.assertIn('name="password" type="password"', html)
        self.assertIn('value="portal-admin"', html)
        self.assertIn('Invalid username or password.', html)
        self.assertIn('Signing in…', html)

    def test_login_page_does_not_prepopulate_administrator_username(self):
        html = render_login_page()

        self.assertIn('name="username" autocomplete="username" value=""', html)
        self.assertNotIn('value="admin"', html)
        self.assertIn('maxlength="64" autofocus', html)
        password = html.split('name="password"', 1)[1].split('</label>', 1)[0]
        self.assertNotIn('autofocus', password)

    def test_json_backup_body_is_not_parsed_as_a_form(self):
        body = b'{"ciphertext":"a+b%2Fc","nested":{"value":"x=y&z"}}'

        self.assertEqual(
            web_portal.parse_portal_body(
                '/secure-configuration-import-preview',
                {'content-type': 'application/json; charset=utf-8'}, body
            ),
            {}
        )
        self.assertEqual(
            web_portal.parse_portal_body(
                '/validate-configuration',
                {'content-type': 'application/json'}, body
            ),
            {'config_json': body.decode()}
        )
        self.assertEqual(
            web_portal.parse_portal_body(
                '/calibrate',
                {'content-type': 'application/x-www-form-urlencoded'},
                b'csrf=token&uuid=0001'
            ),
            {'csrf': 'token', 'uuid': '0001'}
        )

    def test_portal_pages_share_the_same_visual_identity(self):
        pages = (
            render_login_page(),
            web_portal.render_password_change_page('csrf'),
            render_settings_page('csrf', {}),
            render_page('csrf', 'INFO', ('INFO',)),
        )
        for html in pages:
            self.assertIn('HAMD', html)
            self.assertIn('Home Assistant Modular Device', html)
            self.assertIn('class="brand-mark"', html)
            self.assertIn(
                'href="/assets/portal.css?v=' + portal_ui.ASSET_VERSION + '"',
                html,
            )
            self.assertIn(
                'src="/assets/portal.js?v=' + portal_ui.ASSET_VERSION + '"',
                html,
            )
        self.assertIn('--accent:#087e8b', portal_ui.PORTAL_CSS)
        self.assertIn('main{width:auto;margin:0 clamp(16px,4vw,38px)', portal_ui.PORTAL_CSS)
        status = portal_ui.progress('busy', 'Checking…')
        self.assertIn('class="status-spinner"', status)
        self.assertIn('class="status-text">Checking…', status)
        self.assertNotIn('<progress', status)
        self.assertIn('aria-label="Breadcrumb"', pages[-1])

    def test_password_change_requires_current_password(self):
        html = web_portal.render_password_change_page('csrf')
        self.assertIn('<h1>Account</h1>', html)
        self.assertIn('action="/user?action=password"', html)
        self.assertIn('name="current_password"', html)
        self.assertIn('autocomplete="current-password"', html)

    def test_available_remote_release_has_download_and_verify_action(self):
        class MicroPythonText:
            def __str__(self):
                return 'application'

        html = web_portal.render_release_check_html({
            'release_checks_enabled': True,
            # MicroPython str does not provide CPython's str.title().
            'release_available_type': MicroPythonText(),
            'release_available_version': '2.0.0',
            'release_available_notes': 'Universal stable runtime',
        }, 'csrf')
        self.assertIn('action="/check-release"', html)
        self.assertIn('action="/download-release"', html)
        self.assertIn('Download and verify', html)
        self.assertIn('<strong>Application 2.0.0</strong>', html)
        self.assertIn('Universal stable runtime', html)

    def test_password_strength_rejects_predictable_values(self):
        with self.assertRaisesRegex(ValueError, 'common|predictable'):
            credential_security.password_verifier(
                'Password12345678!', bytes(range(16))
            )
        self.assertTrue(credential_security.validate_password_strength(
            'Maple River Lantern Twenty Seven'
        ))

    def test_password_strength_uses_micropython_compatible_character_checks(self):
        self.assertTrue(credential_security._is_lower('a'))
        self.assertTrue(credential_security._is_upper('Z'))
        self.assertTrue(credential_security._is_digit('7'))
        self.assertTrue(credential_security._is_alnum('Q'))
        self.assertFalse(credential_security._is_alnum('!'))
        self.assertTrue(credential_security.validate_password_strength(
            'Setup-Cedar-47!River'
        ))

    def test_password_calculation_reports_progress_for_watchdog_service(self):
        progress = []
        credential_security.set_progress_callback(progress.append)
        try:
            verifier = credential_security.password_verifier(
                'Progress-Cedar-47!River', bytes(range(16))
            )
            self.assertTrue(credential_security.verify_password(
                'Progress-Cedar-47!River', verifier
            ))
        finally:
            credential_security.set_progress_callback()

        self.assertEqual(progress.count(True), 2)
        self.assertEqual(progress[-1], False)

    def test_native_pbkdf2_sha256_known_answer(self):
        self.assertEqual(
            credential_security._pbkdf2_sha256(b'password', b'salt', 1).hex(),
            '120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b',
        )

    def test_pbkdf2_has_no_python_compatibility_fallback(self):
        real_import = builtins.__import__

        def import_without_native(name, *args, **kwargs):
            if name == '_hamd_crypto':
                raise ImportError('native module unavailable')
            return real_import(name, *args, **kwargs)

        with mock.patch('builtins.__import__', side_effect=import_without_native):
            with self.assertRaisesRegex(RuntimeError, 'native PBKDF2 support is required'):
                credential_security._pbkdf2_sha256(b'password', b'salt', 1)

    def test_split_system_pages_mask_but_do_not_render_stored_passwords(self):
        settings = {
            'device_name': 'Controller', 'application_profile': 'whes',
            'release_channel': 'stable', 'portal_username': 'admin',
            'wifi_ssid': 'home-network', 'wifi_password_set': True,
            'wifi_dhcp': True,
            'mqtt_server': 'mqtt.local', 'mqtt_port': 8883,
            'mqtt_username': 'device-user', 'mqtt_password_set': True,
            'portal_transport': 'auto',
        }
        network = render_settings_page('csrf', settings)
        portal = web_portal.render_portal_settings_page('csrf', settings)
        ntp = web_portal.render_ntp_settings_page('csrf', settings)
        mqtt = web_portal.render_mqtt_page('csrf', settings)

        self.assertIn('<h1>Network</h1>', network)
        self.assertIn('<h2>Device identity</h2>', network)
        self.assertIn('<h2>Wi-Fi network</h2>', network)
        self.assertIn('name="portal_username"', network)
        self.assertIn('Automatic (HTTPS with certificate)', portal)
        self.assertIn('name="wifi_ssid"', network)
        self.assertIn('id="wifi-network-select"', network)
        self.assertIn('id="wifi-manual-field"', network)
        self.assertIn('Enter network name manually', network)
        self.assertIn('fetch("/api/wifi-networks"', network)
        self.assertIn('>Network password<input', network)
        self.assertIn('name="wifi_dhcp" type="checkbox" value="true" checked', network)
        self.assertIn('name="wifi_ip_address"', network)
        self.assertIn('name="wifi_subnet_mask"', network)
        self.assertIn('name="wifi_gateway"', network)
        self.assertIn('name="wifi_dns_server"', network)
        self.assertIn('Default gateway', network)
        self.assertNotIn('href="/download-configuration"', network)
        self.assertNotIn('Download configuration', network)
        self.assertIn('id="wifi-static-settings" class="grid" hidden', network)
        self.assertIn('syncNetworkMode()', network)
        self.assertIn('placeholder="&#8226;', network)
        self.assertNotIn('clear_wifi_password', network)
        self.assertIn('name="ntp_servers"', ntp)
        self.assertIn('>MQTT password<input', mqtt)
        self.assertIn('placeholder="&#8226;', mqtt)
        self.assertNotIn('clear_mqtt_password', mqtt)
        for html in (network, portal, ntp, mqtt):
            self.assertNotIn('value="broker-secret"', html)

    def test_post_rc1_operations_pages_expose_safe_workflows(self):
        api = web_portal.render_device_api_page('csrf', {
            'api_enabled': True,
            'api_port': 8444,
            'api_clients': [{
                'label': 'automation', 'scopes': ['read', 'write'],
                'subject': 'CN=automation', 'fingerprint': 'ab' * 32,
                'not_after': '2030-01-01 00:00:00 UTC',
                'expiry_level': 'ok', 'days_remaining': 100,
            }],
        })
        backup = web_portal.render_configuration_backup_page('csrf')
        health = web_portal.render_health_history_page('csrf', {
            'health_history': {
                'counters': {'boots': 3},
                'observations': {'minimum_free_heap': 12345},
                'events': [{'kind': 'boot', 'detail': 'soft_reset'}],
            }
        })

        self.assertIn('Enable the mTLS device API', api)
        self.assertIn('Mutual TLS (required)', api)
        self.assertIn('CN=automation', api)
        self.assertIn('/revoke-api-client', api)
        self.assertIn('/configuration-import-preview', backup)
        self.assertIn('/configuration-import-apply', backup)
        self.assertIn('login verifiers', backup)
        self.assertIn('3</strong>', health)
        self.assertIn('12345', health)
        self.assertIn('soft_reset', health)

    def test_navigation_has_requested_top_levels_submenus_and_breadcrumb(self):
        html = render_settings_page('csrf', {})
        primary = html.split('aria-label="Primary"', 1)[1].split('</nav>', 1)[0]

        for label in ('Status', 'System', 'Module', 'User', 'Maintenance'):
            self.assertIn('>' + label + '</button>', primary)
        self.assertNotIn('nav-menu-trigger" type="button" href=', primary)
        self.assertIn('aria-label="System submenu"', html)
        self.assertIn('.nav-group:hover>.nav-dropdown', portal_ui.PORTAL_CSS)
        self.assertIn('.nav-group:focus-within>.nav-dropdown', portal_ui.PORTAL_CSS)
        self.assertNotIn('subnav-wrap', html)
        self.assertIn('href="/settings" aria-current="page">Network</a>', html)
        self.assertIn('href="/portal-settings">Portal</a>', html)
        self.assertNotIn('href="/wifi-settings">Wi-Fi</a>', html)
        self.assertIn('href="/ntp-settings">Time / Date</a>', html)
        self.assertIn('href="/logging-settings">Logging</a>', html)
        self.assertIn('href="/mqtt">MQTT</a>', html)
        self.assertIn('href="/home-assistant">Home Assistant</a>', html)
        self.assertIn('href="/device-api">Device API</a>', html)
        self.assertIn('href="/configuration-backup">Configuration backup</a>', html)
        self.assertIn('href="/health-history">Health history</a>', html)
        user_menu = html.split(
            'aria-label="User submenu"', 1
        )[1].split('</div>', 1)[0]
        self.assertIn('href="/user">Account</a>', user_menu)
        self.assertNotIn('Change password', user_menu)
        self.assertNotIn('/change-password', html)
        self.assertIn('aria-label="Breadcrumb"', html)
        self.assertIn('<a href="/settings">System</a>', html)
        self.assertIn('aria-hidden="true">\\</span>', html)
        self.assertIn('<main><div class="breadcrumb"', html)

    def test_home_assistant_has_dedicated_configuration_page(self):
        html = web_portal.render_home_assistant_page('csrf', {
            'device_name': 'Controller', 'portal_username': 'admin',
            'wifi_ssid': 'home-network', 'portal_transport': 'auto',
            'mqtt_server': 'mqtt.local', 'mqtt_port': 8883,
            'mqtt_username': 'device-user', 'mqtt_password_set': True,
            'ha_discovery': True,
        })

        self.assertIn('<h1>Home Assistant</h1>', html)
        self.assertIn('action="/home-assistant"', html)
        self.assertIn('name="mqtt_server"', html)
        self.assertIn('name="ha_discovery" checked', html)
        self.assertIn('action="/discover" method="post"', html)
        discovery_card = html.split('<h2>Home Assistant discovery</h2>', 1)[1].split('</section>', 1)[0]
        self.assertIn('Save changes', discovery_card)
        self.assertIn('aria-label="System submenu"', html)
        self.assertNotIn('<h2>MQTT connection</h2>', html)

    def test_mqtt_and_user_have_dedicated_pages(self):
        settings = {
            'device_name': 'Controller', 'portal_username': 'admin',
            'wifi_ssid': 'home-network', 'portal_transport': 'auto',
            'mqtt_server': 'mqtt.local', 'mqtt_port': 8883,
            'mqtt_username': 'device-user', 'mqtt_password_set': True,
            'ha_discovery': True,
        }
        mqtt = web_portal.render_mqtt_page('csrf', settings)
        user = web_portal.render_user_settings_page('csrf', settings, users=(
            {'username': 'admin', 'role': 'administrator', 'enabled': True},
        ))

        self.assertIn('<h1>MQTT</h1>', mqtt)
        self.assertIn('action="/mqtt"', mqtt)
        self.assertIn('<h2>MQTT connection</h2>', mqtt)
        self.assertIn('<a href="/settings">System</a>', mqtt)
        self.assertIn('<h1>Account</h1>', user)
        self.assertIn('action="/user"', user)
        self.assertIn('<h2>Administrator identity</h2>', user)
        self.assertIn('<h2>Change password</h2>', user)
        identity_card = user.split(
            '<h2>Administrator identity</h2>', 1
        )[1].split('</section>', 1)[0]
        self.assertIn('Save changes', identity_card)
        self.assertIn('>Administrator</option>', user)
        self.assertIn('action="/user?action=password"', user)
        self.assertNotIn('/change-password', user)
        self.assertNotIn('/user/password', user)
        self.assertIn('<a href="/user">User</a>', user)
        password_error = web_portal.render_user_settings_page(
            'csrf', settings, password_message='Current password is incorrect.',
            password_error=True
        )
        self.assertIn('Current password is incorrect.', password_error)
        self.assertIn('<h1>Account</h1>', password_error)

    def test_module_configuration_uses_one_structured_json_editor(self):
        html = web_portal.render_module_settings_page(
            'csrf',
            '{"devices":[{"name":"Probe","uuid":"0001","type":{"class":"sensor",'
            '"subclass":"MAX31865"},"entities":{"0":{"key":"temperature",'
            '"class":"temperature","unit":"C"}}}]}'
        )

        self.assertNotIn('>Visual view</button>', html)
        self.assertNotIn('>JSON editor</button>', html)
        self.assertNotIn('id="module-visual"', html)
        self.assertIn('id="module-settings-json"', html)
        self.assertIn('Format JSON', html)
        self.assertIn('JSON.stringify(JSON.parse(raw.value),null,2)', html)
        self.assertIn('aria-label="Module submenu"', html)
        self.assertIn('href="/module-settings" aria-current="page">Configuration</a>', html)
        self.assertIn('href="/diagnostics">Diagnostics</a>', html)

    def test_log_viewer_is_under_maintenance_and_configuration_under_system(self):
        html = web_portal.render_logging_page(
            'csrf', 'INFO', ('ERROR', 'INFO', 'DEBUG'), ['hello']
        )
        maintenance_menu = html.split(
            'aria-label="Maintenance submenu"', 1
        )[1].split('</div>', 1)[0]

        self.assertIn('aria-label="Maintenance submenu"', html)
        self.assertIn('href="/updates">Upgrades</a>', maintenance_menu)
        self.assertNotIn('/updates?check=1', maintenance_menu)
        self.assertIn('href="/certificates">Certificates</a>', maintenance_menu)
        self.assertIn('href="/logging" aria-current="page">Device log</a>', maintenance_menu)
        self.assertIn('<h1>Device log</h1>', html)
        self.assertIn('href="/audit-log">Audit log</a>', maintenance_menu)
        self.assertIn('href="/device-control">Device control</a>', maintenance_menu)
        self.assertNotIn('href="/diagnostics">Diagnostics</a>', maintenance_menu)
        self.assertNotIn('href="/download-diagnostics"', html)
        self.assertIn('id="log-refresh-toggle"', html)
        self.assertIn('>Pause</button>', html)
        self.assertIn('logRefreshPaused=!logRefreshPaused', html)
        self.assertIn('if(logRefreshPaused)return', html)
        self.assertIn('href="/logging-settings"', html)
        self.assertIn('name="log_buffer_lines"', html)
        self.assertIn('>Stored lines <input', html)

        audit = web_portal.render_audit_logging_page(
            'csrf', ['portal login', 'API connection']
        )
        audit_menu = audit.split(
            'aria-label="Maintenance submenu"', 1
        )[1].split('</div>', 1)[0]
        self.assertIn(
            'href="/audit-log" aria-current="page">Audit log</a>', audit_menu
        )
        self.assertIn('<h1>Audit log</h1>', audit)
        self.assertIn('portal login', audit)
        self.assertIn('API connection', audit)
        self.assertIn('href="/download-audit-logs"', audit)
        self.assertIn('fetch("/audit-logs"', audit)

        settings = web_portal.render_logging_settings_page('csrf', {
            'log_buffer_lines': 200, 'syslog_transport': 'udp'
        })
        system_menu = settings.split(
            'aria-label="System submenu"', 1
        )[1].split('</div>', 1)[0]
        self.assertIn('href="/logging-settings" aria-current="page">Logging</a>', system_menu)
        self.assertIn('name="log_buffer_lines"', settings)
        self.assertIn('name="syslog_enabled"', settings)
        self.assertIn('name="syslog_audit_enabled"', settings)
        self.assertIn(
            'Forward device logs to the remote syslog server', settings
        )
        self.assertNotIn('Forward system logs', settings)
        self.assertIn(
            'Forward audit log events to the remote syslog server', settings
        )

        diagnostics = web_portal.render_module_diagnostics_page('csrf', [])
        self.assertIn('href="/download-diagnostics"', diagnostics)
        self.assertNotIn('href="/module-settings">Module configuration</a>', diagnostics)

    def test_overview_shows_package_and_micropython_versions_and_value_tiles(self):
        html = web_portal.render_overview_page('csrf', {
            'device_name': 'Controller', 'wifi_ip': '192.0.2.2', 'mqtt': 'up',
            'uptime_s': 12, 'running_version': '1.9.0',
            'firmware_running_version': 'ham-core-1.9.0-rc.7-mpy1.28.0',
            'base_version': '1.28.0',
        }, [{
            'name': 'Probe', 'type': 'MAX31865',
            'state': {'temperature': 21.5, 'resistance': 1097},
            'diagnostics': {'module_last_ok': True},
        }])

        self.assertIn('<span>Application version</span><strong>1.9.0</strong>', html)
        self.assertIn('<span>Core version</span><strong>1.9.0-rc.7</strong>', html)
        self.assertNotIn('ham-core-', html)
        self.assertNotIn('-mpy1.28.0', html)
        self.assertNotIn('class="metric wide"><span>Core version', html)
        self.assertIn('<h1>Overview</h1>', html)
        self.assertIn('<h2>Device</h2>', html)
        self.assertNotIn('<h2>Device health</h2>', html)
        self.assertNotIn('Open diagnostics', html)
        self.assertIn('<span>MicroPython version</span><strong>1.28.0</strong>', html)
        self.assertIn('MQTT-published values', html)
        self.assertIn('class="published-tile"><span>temperature</span>', html)
        self.assertIn('class="published-tile"><span>resistance</span>', html)
        self.assertNotIn('<h2>Home Assistant</h2>', html)
        self.assertNotIn('action="/discover"', html)

    def test_failed_module_remains_visible_with_setup_error(self):
        module = {
            'uuid': '0001',
            'name': 'Greenstar 8000',
            'type': 'EMS-Boiler',
            'state': {},
            'diagnostics': {
                'module_last_ok': False,
                'module_last_error': 'Setup failed: ESP_ERR_INVALID_STATE',
            },
        }

        overview = web_portal.render_overview_modules([module])
        diagnostics = web_portal.render_modules_html([module], 'csrf')

        self.assertIn('Greenstar 8000', overview)
        self.assertIn('Setup failed: ESP_ERR_INVALID_STATE', overview)
        self.assertIn('attention', overview)
        self.assertIn('Greenstar 8000', diagnostics)
        self.assertIn('Setup failed: ESP_ERR_INVALID_STATE', diagnostics)
        self.assertIn('attention', diagnostics)
        self.assertNotIn('>check</span>', diagnostics)

    def test_module_health_badges_are_consistent_across_status_pages(self):
        states = (
            ({'module_last_ok': True}, 'healthy'),
            ({'module_last_ok': False}, 'attention'),
            ({'module_rs485_last_ok': False}, 'attention'),
            ({}, 'active'),
        )
        for module_diagnostics, expected in states:
            module = {
                'uuid': '0001', 'name': 'Probe', 'type': 'sensor',
                'state': {}, 'diagnostics': module_diagnostics,
            }
            overview = web_portal.render_overview_modules([module])
            diagnostics = web_portal.render_modules_html([module], 'csrf')
            badge = 'class="badge'
            self.assertIn(badge, overview)
            self.assertIn('>' + expected + '</span>', overview)
            self.assertIn('>' + expected + '</span>', diagnostics)

    def test_single_section_actions_stay_inside_their_cards(self):
        settings = {
            'portal_transport': 'auto', 'portal_port': 8443,
            'ntp_servers': ('pool.ntp.org',), 'mqtt_port': 8883,
            'portal_username': 'admin',
        }
        pages = (
            (web_portal.render_portal_settings_page('csrf', settings),
             'Portal access', 'Save changes'),
            (web_portal.render_ntp_settings_page('csrf', settings),
             'Time synchronisation', 'Save changes'),
            (web_portal.render_mqtt_page('csrf', settings),
             'MQTT connection', 'Save changes'),
            (web_portal.render_user_settings_page('csrf', settings),
             'Administrator identity', 'Save changes'),
        )
        for html, heading, action in pages:
            card = html.split('<h2>' + heading + '</h2>', 1)[1].split(
                '</section>', 1
            )[0]
            self.assertIn(action, card)

    def test_login_session_and_logout_flow(self):
        class Reader:
            def __init__(self, request):
                self.data = request

            async def readline(self):
                index = self.data.find(b'\n')
                if index < 0:
                    value, self.data = self.data, b''
                    return value
                value, self.data = self.data[:index + 1], self.data[index + 1:]
                return value

            async def read(self, size):
                chunk = self.data[:size]
                self.data = self.data[size:]
                return chunk

        class Writer:
            def __init__(self):
                self.chunks = []

            def write(self, data):
                self.chunks.append(data)

            async def drain(self):
                pass

            def close(self):
                pass

            async def wait_closed(self):
                pass

        async def exercise_flow():
            captured = {}
            original_start_server = web_portal.asyncio.start_server
            original_tls = web_portal.make_tls_context

            async def fake_start_server(handler, *args, **kwargs):
                captured['handler'] = handler
                return object()

            async def request(raw):
                writer = Writer()
                await captured['handler'](Reader(raw), writer)
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                return b''.join(writer.chunks).decode()

            web_portal.asyncio.start_server = fake_start_server
            web_portal.make_tls_context = lambda *args: object()
            try:
                verifier = credential_security.password_verifier(
                    'Correct-Cedar-47!River', bytes(range(16))
                )
                changed_verifiers = []
                changed_settings = []
                portal_actions = []
                portal_events = []
                network_confirmations = []
                factory_resets = []
                restart_requests = []
                shutdown_requests = []

                def get_settings():
                    return {
                        'device_name': 'Controller', 'application_profile': 'whes',
                        'release_channel': 'stable', 'portal_username': 'admin',
                        'wifi_ssid': 'home-network', 'wifi_password_set': True,
                        'mqtt_server': '', 'mqtt_port': 8883,
                        'mqtt_username': '', 'mqtt_password_set': False,
                    }

                def set_settings(params):
                    changed_settings.append(params)
                    return 'Settings saved; restart when ready'

                def set_password(password):
                    updated = credential_security.password_verifier(
                        password, bytes(range(16, 32))
                    )
                    changed_verifiers.append(updated)
                    return updated

                def handle_action(action, params):
                    portal_actions.append((action, params))
                    if action == 'check-release':
                        return {
                            'task_id': 'release-check-1',
                            'message': 'Checking the signed release channel',
                        }
                    return ''

                await web_portal.start_web_portal(PortalDependencies(
                    {
                        'username': 'admin', 'password_verifier': verifier,
                        'https': True, 'password_change_required': True,
                        'password_setter': set_password
                    },
                    {
                    'logs.get': lambda: ['initial portal log'],
                    'audit.get': lambda: ['successful login', 'API connection'],
                    'logs.level.get': lambda: 'INFO',
                    'logs.level.set': lambda level: None,
                    'events.log': lambda *args: portal_events.append(args),
                    'status.get': lambda: {'device_name': 'Controller'},
                    'actions.apply': handle_action,
                    'settings.get': get_settings,
                    'settings.apply': set_settings,
                    'network.confirm': (
                        lambda: network_confirmations.append(True) or True
                    ),
                    'factory_reset.request': (
                        lambda password: factory_resets.append(password) or True
                    ),
                    'restart.status': lambda: {
                        'required': True, 'reason_count': 1,
                        'reasons': ['System settings changed'],
                    },
                    'restart.request': lambda: (
                        restart_requests.append(True) or {
                            'message': 'Committed changes are being activated.',
                            'login_url': '/login',
                        }
                    ),
                    'shutdown.request': lambda: (
                        shutdown_requests.append(True) or {
                            'message': 'The device is shutting down.',
                        }
                    ),
                    }
                ))

                persistent = await request(
                    ('GET /login HTTP/1.1\r\n\r\nGET /assets/portal.css?v=' +
                     portal_ui.ASSET_VERSION +
                     ' HTTP/1.1\r\nConnection: close\r\n\r\n').encode()
                )
                self.assertEqual(persistent.count('HTTP/1.1 200 OK'), 2)
                self.assertIn('Connection: keep-alive', persistent)
                self.assertIn('Connection: close', persistent)

                unauthorized = await request(b'GET / HTTP/1.1\r\n\r\n')
                self.assertIn('401 Unauthorized', unauthorized)
                self.assertIn('name="password" type="password"', unauthorized)
                self.assertIn(
                    'name="username" autocomplete="username" value=""',
                    unauthorized
                )

                body = b'username=admin&password=Correct-Cedar-47%21River'
                login = await request(
                    b'POST /login HTTP/1.1\r\nContent-Length: ' +
                    str(len(body)).encode() + b'\r\n\r\n' + body
                )
                self.assertIn('303 See Other', login)
                self.assertIn('Location: /user', login)
                self.assertEqual(network_confirmations, [True])
                login_event = next(
                    event for event in portal_events
                    if event[1] == 'Portal authentication'
                )
                self.assertTrue(login_event[2]['audit'])
                self.assertEqual(login_event[3], 'INFO')
                cookie_header = next(
                    line for line in login.split('\r\n')
                    if line.startswith('Set-Cookie: ham_session=')
                )
                session_id = cookie_header.split('ham_session=', 1)[1].split(';', 1)[0]

                locked = await request(
                    ('GET / HTTP/1.1\r\nCookie: ham_session=' + session_id +
                     '\r\n\r\n').encode()
                )
                self.assertIn('Location: /user', locked)

                account_page = await request(
                    ('GET /user HTTP/1.1\r\nCookie: ham_session=' + session_id +
                     '\r\n\r\n').encode()
                )
                csrf_token = account_page.split(
                    'name="csrf" value="', 1
                )[1].split('"', 1)[0]
                self.assertNotEqual(csrf_token, session_id)

                wrong_change_body = (
                    'csrf=' + csrf_token + '&current_password=incorrect'
                    '&new_password=New-Secure-Cedar-48%21'
                    '&confirm_password=New-Secure-Cedar-48%21'
                ).encode()
                wrong_change = await request(
                    ('POST /user?action=password HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\nContent-Length: ' +
                     str(len(wrong_change_body)) + '\r\n\r\n').encode() +
                    wrong_change_body
                )
                self.assertIn('400 Bad Request', wrong_change)
                self.assertIn('Current password is incorrect.', wrong_change)
                self.assertEqual(changed_verifiers, [])

                change_body = (
                    'csrf=' + csrf_token +
                    '&current_password=Correct-Cedar-47%21River'
                    '&new_password=New-Secure-Cedar-48%21'
                    '&confirm_password=New-Secure-Cedar-48%21'
                ).encode()
                changed = await request(
                    ('POST /user?action=password HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\nContent-Length: ' + str(len(change_body)) +
                     '\r\n\r\n').encode() + change_body
                )
                self.assertIn('303 See Other', changed)
                self.assertEqual(len(changed_verifiers), 1)
                self.assertTrue(credential_security.verify_password(
                    'New-Secure-Cedar-48!',
                    changed_verifiers[0]
                ))
                changed_cookie = next(
                    line for line in changed.split('\r\n')
                    if line.startswith('Set-Cookie: ham_session=')
                )
                session_id = changed_cookie.split(
                    'ham_session=', 1
                )[1].split(';', 1)[0]

                authorized = await request(
                    ('GET / HTTP/1.1\r\nCookie: ham_session=' + session_id +
                     '\r\n\r\n').encode()
                )
                self.assertIn('200 OK', authorized)
                self.assertIn('Sign out', authorized)
                self.assertIn(
                    'aria-label="Signed in as admin, administrator"', authorized
                )
                self.assertIn('Controller', authorized)
                self.assertIn('<h1>Overview</h1>', authorized)
                self.assertNotIn('initial portal log', authorized)
                csrf_token = authorized.split(
                    'name="csrf" value="', 1
                )[1].split('"', 1)[0]

                stylesheet = await request(
                    ('GET /assets/portal.css?v=' + portal_ui.ASSET_VERSION +
                     ' HTTP/1.1\r\n\r\n').encode()
                )
                self.assertIn('200 OK', stylesheet)
                self.assertIn(
                    'Cache-Control: public, max-age=31536000, immutable',
                    stylesheet
                )
                self.assertIn('.nav-group:hover>.nav-dropdown', stylesheet)

                javascript = await request(
                    ('GET /assets/portal.js?v=' + portal_ui.ASSET_VERSION +
                     ' HTTP/1.1\r\n\r\n').encode()
                )
                self.assertIn('200 OK', javascript)
                self.assertIn(
                    'Cache-Control: public, max-age=31536000, immutable',
                    javascript
                )
                self.assertIn('nav-menu-trigger', javascript)

                diagnostics = await request(
                    ('GET /diagnostics HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\n\r\n').encode()
                )
                self.assertIn('<h1>Diagnostics</h1>', diagnostics)
                self.assertIn('aria-label="Module submenu"', diagnostics)

                debug_body = (
                    'csrf=' + csrf_token + '&uuid=0001&enabled=true'
                ).encode()
                debug_response = await request(
                    ('POST /ems-debug HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\nContent-Length: ' +
                     str(len(debug_body)) + '\r\n\r\n').encode() + debug_body
                )
                self.assertIn('303 See Other', debug_response)
                self.assertIn('Location: /diagnostics', debug_response)
                self.assertIn(
                    ('ems-debug', {
                        'csrf': csrf_token,
                        'uuid': '0001',
                        'enabled': 'true',
                    }),
                    portal_actions,
                )

                logging = await request(
                    ('GET /logging HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\n\r\n').encode()
                )
                self.assertIn('<h1>Device log</h1>', logging)
                self.assertIn('initial portal log', logging)
                self.assertIn('name="level"', logging)

                audit_logging = await request(
                    ('GET /audit-log HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\n\r\n').encode()
                )
                self.assertIn('<h1>Audit log</h1>', audit_logging)
                self.assertIn('successful login', audit_logging)
                audit_feed = await request(
                    ('GET /audit-logs HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\n\r\n').encode()
                )
                self.assertIn('successful login\nAPI connection', audit_feed)
                request_event = next(
                    event for event in portal_events
                    if event[1] == 'Web portal request'
                )
                self.assertEqual(request_event[3], 'DEBUG')
                self.assertNotIn('audit', request_event[2])

                home_assistant = await request(
                    ('GET /home-assistant HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\n\r\n').encode()
                )
                self.assertIn('<h1>Home Assistant</h1>', home_assistant)
                self.assertIn('action="/home-assistant"', home_assistant)

                mqtt = await request(
                    ('GET /mqtt HTTP/1.1\r\nCookie: ham_session=' + session_id +
                     '\r\n\r\n').encode()
                )
                self.assertIn('<h1>MQTT</h1>', mqtt)
                self.assertIn('action="/mqtt"', mqtt)

                user_page = await request(
                    ('GET /user HTTP/1.1\r\nCookie: ham_session=' + session_id +
                     '\r\n\r\n').encode()
                )
                self.assertIn('<h1>Account</h1>', user_page)
                self.assertIn('action="/user"', user_page)
                self.assertIn('action="/user?action=password"', user_page)
                self.assertNotIn('/change-password', user_page)
                self.assertNotIn('/user/password', user_page)

                removed_password_page = await request(
                    ('GET /change-password HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\n\r\n').encode()
                )
                self.assertIn('404 Not Found', removed_password_page)

                removed_user_password_page = await request(
                    ('GET /user/password HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\n\r\n').encode()
                )
                self.assertIn('404 Not Found', removed_user_password_page)

                normal_wrong_body = (
                    'csrf=' + csrf_token + '&current_password=incorrect'
                    '&new_password=Another-Secure-Cedar-49%21'
                    '&confirm_password=Another-Secure-Cedar-49%21'
                ).encode()
                normal_wrong = await request(
                    ('POST /user?action=password HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\nContent-Length: ' +
                     str(len(normal_wrong_body)) + '\r\n\r\n').encode() +
                    normal_wrong_body
                )
                self.assertIn('400 Bad Request', normal_wrong)
                self.assertIn('<h1>Account</h1>', normal_wrong)
                self.assertIn('<h2>Administrator identity</h2>', normal_wrong)
                self.assertIn('<h2>Change password</h2>', normal_wrong)
                self.assertIn('Current password is incorrect.', normal_wrong)

                settings_page = await request(
                    ('GET /settings HTTP/1.1\r\nCookie: ham_session=' + session_id +
                     '\r\n\r\n').encode()
                )
                self.assertIn('<h1>Network</h1>', settings_page)

                for route, heading in (
                    ('/portal-settings', 'Portal'),
                    ('/wifi-settings', 'Network'),
                    ('/ntp-settings', 'Time / Date'),
                    ('/logging-settings', 'Logging'),
                ):
                    page = await request(
                        ('GET ' + route + ' HTTP/1.1\r\nCookie: ham_session=' +
                         session_id + '\r\n\r\n').encode()
                    )
                    self.assertIn('<h1>' + heading + '</h1>', page)

                action_count = len(portal_actions)
                automatic_check = await request(
                    ('GET /updates?check=1 HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\n\r\n').encode()
                )
                self.assertIn('200 OK', automatic_check)
                self.assertIn('<h1>Upgrades</h1>', automatic_check)
                self.assertIn('Not checked', automatic_check)
                self.assertEqual(len(portal_actions), action_count)
                settings_body = (
                    'csrf=' + csrf_token + '&device_name=New+Controller'
                    '&wifi_ssid=new-network&wifi_dhcp=true'
                    '&mqtt_server=mqtt.local&mqtt_port=8883'
                    '&mqtt_username=device-user&portal_username=admin'
                    '&release_channel=stable'
                ).encode()
                settings_saved = await request(
                    ('POST /settings HTTP/1.1\r\nCookie: ham_session=' + session_id +
                     '\r\nContent-Length: ' + str(len(settings_body)) +
                     '\r\n\r\n').encode() + settings_body
                )
                self.assertIn('200 OK', settings_saved)
                self.assertIn('Settings saved; restart when ready', settings_saved)
                self.assertIn('action="/restart-device"', settings_saved)
                self.assertNotIn('Max-Age=0', settings_saved)
                self.assertEqual(changed_settings[0]['wifi_ssid'], 'new-network')

                restart_status = await request(
                    ('GET /api/restart-required HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\n\r\n').encode()
                )
                self.assertIn('"required": true', restart_status)
                restart_body = ('csrf=' + csrf_token).encode()
                restart_response = await request(
                    ('POST /restart-device HTTP/1.1\r\nCookie: ham_session=' +
                     session_id + '\r\nContent-Length: ' +
                     str(len(restart_body)) + '\r\n\r\n').encode() + restart_body
                )
                self.assertIn('Device restarting', restart_response)
                self.assertIn('Max-Age=0', restart_response)
                self.assertEqual(restart_requests, [True])

                expired = await request(
                    ('GET / HTTP/1.1\r\nCookie: ham_session=' + session_id +
                     '\r\n\r\n').encode()
                )
                self.assertIn('401 Unauthorized', expired)

                relogin_body = b'username=admin&password=New-Secure-Cedar-48%21'
                relogin = await request(
                    b'POST /login HTTP/1.1\r\nContent-Length: ' +
                    str(len(relogin_body)).encode() + b'\r\n\r\n' + relogin_body
                )
                session_id = next(
                    line for line in relogin.split('\r\n')
                    if line.startswith('Set-Cookie: ham_session=')
                ).split('ham_session=', 1)[1].split(';', 1)[0]

                relogin_page = await request(
                    ('GET / HTTP/1.1\r\nCookie: ham_session=' + session_id +
                     '\r\n\r\n').encode()
                )
                csrf_token = relogin_page.split(
                    'name="csrf" value="', 1
                )[1].split('"', 1)[0]

                logout_body = ('csrf=' + csrf_token).encode()
                logout = await request(
                    ('POST /logout HTTP/1.1\r\nCookie: ham_session=' + session_id +
                     '\r\nContent-Length: ' + str(len(logout_body)) +
                     '\r\n\r\n').encode() + logout_body
                )
                self.assertIn('303 See Other', logout)
                self.assertIn('Location: /login', logout)
                self.assertIn('Max-Age=0', logout)

                reset_login = await request(
                    b'POST /login HTTP/1.1\r\nContent-Length: ' +
                    str(len(relogin_body)).encode() + b'\r\n\r\n' + relogin_body
                )
                reset_session = next(
                    line for line in reset_login.split('\r\n')
                    if line.startswith('Set-Cookie: ham_session=')
                ).split('ham_session=', 1)[1].split(';', 1)[0]
                reset_page = await request(
                    ('GET /factory-default HTTP/1.1\r\nCookie: ham_session=' +
                     reset_session + '\r\n\r\n').encode()
                )
                self.assertIn('<h1>Device control</h1>', reset_page)
                self.assertIn('action="/restart-device"', reset_page)
                self.assertIn('action="/shutdown-device"', reset_page)
                self.assertIn('name="reset_confirmation"', reset_page)
                self.assertIn('The signed core, active application', reset_page)
                self.assertIn('>WiFi AP Password<input', reset_page)
                self.assertIn('>Confirm WiFi AP Password<input', reset_page)
                self.assertNotIn('New setup Wi-Fi password', reset_page)
                reset_csrf = reset_page.split(
                    'name="csrf" value="', 1
                )[1].split('"', 1)[0]
                reset_body = (
                    'csrf=' + reset_csrf +
                    '&current_password=New-Secure-Cedar-48%21'
                    '&setup_password=Setup-Maple-53%21Harbour'
                    '&confirm_setup_password=Setup-Maple-53%21Harbour'
                    '&reset_confirmation=RESET'
                ).encode()
                reset_response = await request(
                    ('POST /factory-default HTTP/1.1\r\nCookie: ham_session=' +
                     reset_session + '\r\nContent-Length: ' +
                     str(len(reset_body)) + '\r\n\r\n').encode() + reset_body
                )
                self.assertIn('200 OK', reset_response)
                self.assertIn('Factory reset armed', reset_response)
                self.assertIn('Max-Age=0', reset_response)
                self.assertEqual(factory_resets, ['Setup-Maple-53!Harbour'])

                shutdown_login = await request(
                    b'POST /login HTTP/1.1\r\nContent-Length: ' +
                    str(len(relogin_body)).encode() + b'\r\n\r\n' + relogin_body
                )
                shutdown_session = next(
                    line for line in shutdown_login.split('\r\n')
                    if line.startswith('Set-Cookie: ham_session=')
                ).split('ham_session=', 1)[1].split(';', 1)[0]
                control_page = await request(
                    ('GET /device-control HTTP/1.1\r\nCookie: ham_session=' +
                     shutdown_session + '\r\n\r\n').encode()
                )
                self.assertIn('<h1>Device control</h1>', control_page)
                self.assertIn('action="/restart-device"', control_page)
                self.assertIn('action="/shutdown-device"', control_page)
                self.assertIn('class="actions power-actions"', control_page)
                self.assertIn('class="danger" type="submit">Shut down device', control_page)
                self.assertIn('<h2>Factory default</h2>', control_page)
                shutdown_csrf = control_page.split(
                    'name="csrf" value="', 1
                )[1].split('"', 1)[0]
                shutdown_body = ('csrf=' + shutdown_csrf).encode()
                shutdown_response = await request(
                    ('POST /shutdown-device HTTP/1.1\r\nCookie: ham_session=' +
                     shutdown_session + '\r\nContent-Length: ' +
                     str(len(shutdown_body)) + '\r\n\r\n').encode() +
                    shutdown_body
                )
                self.assertIn('Device shutting down', shutdown_response)
                self.assertIn(
                    'No configuration or installed software is erased.',
                    shutdown_response
                )
                self.assertIn('Max-Age=0', shutdown_response)
                self.assertEqual(shutdown_requests, [True])

                async def viewer_authenticator(login_username, login_password):
                    if (
                        login_username == 'viewer' and
                        login_password == 'Viewer-Cedar-47!River'
                    ):
                        return {'username': 'viewer', 'role': 'viewer'}
                    return None

                await web_portal.start_web_portal(PortalDependencies(
                    {
                        'username': 'admin', 'authenticator': viewer_authenticator,
                        'https': True, 'password_change_required': False,
                    },
                    {
                        'logs.get': lambda: [],
                        'logs.level.get': lambda: 'INFO',
                        'logs.level.set': lambda level: None,
                        'events.log': lambda *args: None,
                        'status.get': lambda: {'device_name': 'Controller'},
                        'modules.list': lambda: [{
                            'uuid': '0001', 'name': 'AC voltage',
                            'type': 'Grove-AC-Voltage', 'state': {},
                            'diagnostics': {'module_last_ok': True},
                            'calibratable': True,
                        }],
                        'actions.apply': handle_action,
                    }
                ))
                viewer_body = (
                    b'username=viewer&password=Viewer-Cedar-47%21River'
                )
                viewer_login = await request(
                    b'POST /login HTTP/1.1\r\nContent-Length: ' +
                    str(len(viewer_body)).encode() + b'\r\n\r\n' + viewer_body
                )
                viewer_session = next(
                    line for line in viewer_login.split('\r\n')
                    if line.startswith('Set-Cookie: ham_session=')
                ).split('ham_session=', 1)[1].split(';', 1)[0]
                viewer_page = await request(
                    ('GET /diagnostics HTTP/1.1\r\nCookie: ham_session=' +
                     viewer_session + '\r\n\r\n').encode()
                )
                self.assertIn(
                    'aria-label="Signed in as viewer, viewer"', viewer_page
                )
                viewer_logout_form = viewer_page.split(
                    'action="/logout"', 1
                )[1].split('</form>', 1)[0]
                self.assertNotIn('disabled', viewer_logout_form)
                viewer_csrf = viewer_logout_form.split(
                    'name="csrf" value="', 1
                )[1].split('"', 1)[0]
                viewer_logout_body = ('csrf=' + viewer_csrf).encode()
                viewer_logout = await request(
                    ('POST /logout HTTP/1.1\r\nCookie: ham_session=' +
                     viewer_session + '\r\nContent-Length: ' +
                     str(len(viewer_logout_body)) + '\r\n\r\n').encode() +
                    viewer_logout_body
                )
                self.assertIn('303 See Other', viewer_logout)
                self.assertIn('Location: /login', viewer_logout)
                self.assertIn('Max-Age=0', viewer_logout)
                viewer_expired = await request(
                    ('GET /diagnostics HTTP/1.1\r\nCookie: ham_session=' +
                     viewer_session + '\r\n\r\n').encode()
                )
                self.assertIn('401 Unauthorized', viewer_expired)
            finally:
                web_portal.asyncio.start_server = original_start_server
                web_portal.make_tls_context = original_tls

        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                asyncio.run(exercise_flow())
            finally:
                os.chdir(previous_cwd)

    def test_requested_loglevel_must_be_allowed(self):
        levels = ('ERROR', 'INFO', 'DEBUG')
        self.assertEqual(requested_loglevel('/set-loglevel?level=debug', levels), 'DEBUG')
        self.assertIsNone(requested_loglevel('/set-loglevel?level=TRACE', levels))

    def test_apply_loglevel_change_forces_audit_log(self):
        levels = []
        logs = []

        apply_loglevel_change(
            'ERROR',
            lambda level: levels.append(level),
            lambda mode, action, data, logtype: logs.append((mode, action, data, logtype))
        )

        self.assertEqual(levels, ['ERROR'])
        self.assertEqual(logs[0][0], 'Local')
        self.assertEqual(logs[0][1], 'Web portal')
        self.assertEqual(logs[0][2]['log'], 'Log level changed to ERROR')
        self.assertTrue(logs[0][2]['force'])
        self.assertEqual(logs[0][3], 'INFO')

    def test_combined_logging_change_applies_level_and_retained_lines(self):
        levels = []
        limits = []
        logs = []

        result = apply_logging_change(
            'debug', '275', ('ERROR', 'INFO', 'DEBUG'), levels.append,
            limits.append,
            lambda mode, action, data, logtype: logs.append(
                (mode, action, data, logtype)
            )
        )

        self.assertEqual(result, ('DEBUG', 275))
        self.assertEqual(levels, ['DEBUG'])
        self.assertEqual(limits, [275])
        self.assertIn('275 retained lines', logs[0][2]['log'])
        with self.assertRaisesRegex(ValueError, 'between 0 and 500'):
            apply_logging_change(
                'INFO', 501, ('ERROR', 'INFO', 'DEBUG'), levels.append,
                limits.append, lambda *_args: None
            )

    def test_apply_portal_action_logs_action_result_once(self):
        actions = []
        logs = []

        result = apply_portal_action(
            'calibrate',
            '/calibrate?uuid=0001&known_voltage=240',
            lambda action, params: actions.append((action, params)) or 'Calibration set',
            lambda mode, action, data, logtype: logs.append((mode, action, data, logtype))
        )

        self.assertEqual(result, 'Calibration set')
        self.assertEqual(actions[0][0], 'calibrate')
        self.assertEqual(actions[0][1]['uuid'], '0001')
        self.assertEqual(actions[0][1]['known_voltage'], '240')
        self.assertEqual(logs[0][0], 'Local')
        self.assertEqual(logs[0][1], 'Web portal')
        self.assertEqual(logs[0][2]['log'], 'Calibration set')
        self.assertTrue(logs[0][2]['force'])
        self.assertEqual(logs[0][3], 'INFO')

    def test_client_disconnect_errors_are_recognized(self):
        self.assertTrue(is_client_disconnect_error(OSError(-29312, 'MBEDTLS_ERR_SSL_CONN_EOF')))
        self.assertTrue(is_client_disconnect_error(OSError('MBEDTLS_ERR_SSL_CONN_EOF')))
        self.assertTrue(is_client_disconnect_error(OSError(-28288, 'MBEDTLS_ERR_SSL_BAD_PROTOCOL_VERSION')))
        self.assertTrue(is_client_disconnect_error(OSError(-30592, 'MBEDTLS_ERR_SSL_FATAL_ALERT_MESSAGE')))
        self.assertTrue(is_client_disconnect_error(OSError('MBEDTLS_ERR_SSL_FATAL_ALERT_MESSAGE')))
        self.assertTrue(is_client_disconnect_error(OSError(113, 'ECONNABORTED')))
        self.assertTrue(is_client_disconnect_error(OSError(104, 'ECONNRESET')))
        self.assertFalse(is_client_disconnect_error(OSError(12, 'ENOMEM')))

    def test_unhandled_portal_route_error_has_an_http_fallback(self):
        source = (Path(__file__).resolve().parents[1] / 'web_portal.py').read_text()
        self.assertIn("'500 Internal Server Error'", source)
        self.assertIn(
            'Portal request failed. See Maintenance > Device log for details.',
            source,
        )

    def test_response_sets_content_length(self):
        raw = response('200 OK', 'hello', 'text/plain')
        self.assertIn('Content-Length: 5', raw)
        self.assertTrue(raw.endswith('\r\n\r\nhello'))

    def test_download_response_is_text_attachment(self):
        raw = download_response('first\nsecond')

        self.assertIn('HTTP/1.1 200 OK', raw)
        self.assertIn('Content-Type: text/plain; charset=utf-8', raw)
        self.assertIn(
            'Content-Disposition: attachment; filename="ha-device-logs.txt"',
            raw
        )
        self.assertIn('Content-Length: 12', raw)
        self.assertTrue(raw.endswith('\r\n\r\nfirst\nsecond'))

    def test_buffered_response_writes_complete_body_without_chunk_drains(self):
        class Writer:
            def __init__(self):
                self.chunks = []
                self.drains = 0

            def write(self, data):
                self.chunks.append(data)

            async def drain(self):
                self.drains += 1

        writer = Writer()
        body = '£' * 2000

        asyncio.run(write_buffered_response(
            writer, '200 OK', body, 'text/plain', keep_alive=True
        ))

        raw = b''.join(writer.chunks)
        headers, payload = raw.split(b'\r\n\r\n', 1)
        self.assertIn(('Content-Length: ' + str(len(body.encode()))).encode(), headers)
        self.assertIn(b'X-Content-Type-Options: nosniff', headers)
        self.assertIn(b'X-Frame-Options: DENY', headers)
        self.assertIn(b"Content-Security-Policy: frame-ancestors 'none'", headers)
        self.assertIn(b'Connection: keep-alive', headers)
        self.assertEqual(payload.decode(), body)
        self.assertEqual(writer.drains, 1)

    def test_overview_uses_targeted_live_refresh(self):
        html = render_page(
            'abc', 'INFO', ('ERROR', 'INFO', 'DEBUG'), [], 3000,
            {'device_name': 'ESP32-S3'}, [], '', 3000
        )

        self.assertIn('fetch("/api/overview"', html)
        self.assertIn('setInterval(refreshOverview,3000)', html)
        self.assertNotIn('id="logs"', html)
        self.assertNotIn('id="update-upload-form"', html)

    def test_page_parts_compose_the_complete_response(self):
        parts = render_page_parts(
            'abc', 'INFO', ('ERROR', 'INFO', 'DEBUG'), [], 3000,
            {'device_name': 'ESP32-S3'}, [], '', 12000
        )
        self.assertEqual(len(parts), 1)
        self.assertEqual(
            ''.join(parts),
            render_page(
                'abc', 'INFO', ('ERROR', 'INFO', 'DEBUG'), [], 3000,
                {'device_name': 'ESP32-S3'}, [], '', 12000
            )
        )

    def test_large_module_live_section_is_split_into_small_fragments(self):
        module = {
            'uuid': '0001',
            'name': 'Large module',
            'type': 'Test',
            'state': {'state_' + str(index): index for index in range(40)},
            'diagnostics': {
                'diagnostic_' + str(index): index for index in range(40)
            }
        }
        parts = web_portal.render_live_sections_parts({}, [module], 'abc')

        self.assertGreater(len(parts), 80)
        self.assertLess(max(len(part) for part in parts), 1500)
        self.assertEqual(
            ''.join(parts),
            web_portal.render_live_sections_html({}, [module], 'abc')
        )

    def test_redirect_sets_location(self):
        raw = redirect('/login')
        self.assertIn('HTTP/1.1 303 See Other', raw)
        self.assertIn('Location: /login', raw)

    def test_render_logs_html_escapes_html(self):
        self.assertEqual(render_logs_html(['one < two']), 'one &lt; two')

    def test_friendly_labels_apply_to_all_module_health_fields(self):
        self.assertEqual(friendly_label('module_last_ok'), 'Last operation OK')
        self.assertEqual(friendly_label('module_last_error'), 'Last error')
        self.assertEqual(friendly_label('module_last_read_ms'), 'Read duration (ms)')
        self.assertEqual(friendly_label('module_last_publish_age_s'), 'HA publish age (s)')
        self.assertEqual(friendly_label('module_consecutive_errors'), 'Consecutive errors')
        self.assertEqual(friendly_label('module_custom_value'), 'custom value')

    def test_friendly_labels_preserve_protocol_acronyms(self):
        self.assertEqual(friendly_label('ems_crc_errors'), 'EMS CRC errors')
        self.assertEqual(friendly_label('rs485_last_ok'), 'RS485 last request OK')
        self.assertEqual(friendly_label('adc_rms'), 'ADC RMS')

    def test_render_log_text_does_not_escape_html_entities(self):
        self.assertEqual(render_log_text(['{"state": "ON"}']), '{"state": "ON"}')

    def test_enabled_ems_debug_renders_disable_control(self):
        html = web_portal.render_modules_html([{
            'uuid': '0001',
            'name': 'Greenstar 8000',
            'type': 'EMS-Boiler',
            'state': {},
            'diagnostics': {'module_last_ok': True},
            'debug_frames': True,
        }], 'csrf')

        self.assertIn('action="/ems-debug"', html)
        self.assertIn('name="enabled" value="false"', html)
        self.assertIn('Disable debug frames', html)
        self.assertNotIn('Enable debug frames', html)

    def test_viewer_module_actions_are_visible_but_disabled(self):
        html = web_portal.render_modules_html([{
            'uuid': '0001',
            'name': 'AC voltage',
            'type': 'Grove-AC-Voltage',
            'state': {},
            'diagnostics': {'module_last_ok': True},
            'calibratable': True,
            'debug_frames': False,
        }], 'csrf', 'viewer')

        self.assertIn('action="/calibrate"', html)
        self.assertIn('action="/ems-debug"', html)
        self.assertEqual(html.count('disabled aria-disabled="true"'), 8)
        self.assertIn('<button type="submit" title="Calculate a new in-memory calibration multiplier for this module." disabled aria-disabled="true"', html)

    def test_operator_module_actions_remain_enabled(self):
        html = web_portal.render_modules_html([{
            'uuid': '0001', 'name': 'AC voltage',
            'type': 'Grove-AC-Voltage', 'state': {},
            'diagnostics': {}, 'calibratable': True,
        }], 'csrf', 'operator')

        calibration = html.split('action="/calibrate"', 1)[1].split(
            '</form>', 1
        )[0]
        self.assertNotIn('disabled', calibration)

    def test_personalised_page_shows_identity_and_restricts_actions(self):
        html = portal_ui.shell(
            'Test', 'module_diagnostics',
            '<form action="/calibrate" method="post"><button>Calibrate</button></form>'
            '<a class="button" href="/download-diagnostics">Download</a>',
            'csrf'
        )
        personalised = portal_ui.personalise_page(
            html, 'viewer&lt;unsafe', 'viewer'
        )

        self.assertIn('viewer&amp;lt;unsafe', personalised)
        self.assertIn('title="viewer&amp;lt;unsafe · Viewer privileges"', personalised)
        self.assertIn('<span aria-hidden="true">VU</span>', personalised)
        self.assertIn('class="portal-identity" tabindex="0"', personalised)
        self.assertIn('<button disabled aria-disabled="true"', personalised)
        self.assertIn('>Download</a>', personalised)
        self.assertNotIn('href="/download-diagnostics"', personalised)
        self.assertIn('action="/logout"', personalised)
        logout = personalised.split('action="/logout"', 1)[1].split(
            '</form>', 1
        )[0]
        self.assertNotIn('disabled', logout)
        self.assertLess(
            personalised.index('class="portal-identity"'),
            personalised.index('action="/logout"')
        )
        navigation = personalised.split(
            '<nav id="portal-nav"', 1
        )[1].split('</nav>', 1)[0]
        self.assertIn('class="portal-identity"', navigation)

    def test_identity_badge_uses_first_letters_of_username_words(self):
        badge = portal_ui.identity_badge('Ian Walton', 'administrator')

        self.assertIn('<span aria-hidden="true">IW</span>', badge)
        self.assertIn('title="Ian Walton · Administrator privileges"', badge)

        punctuation = portal_ui.identity_badge(
            'portal-admin_2', 'administrator'
        )
        self.assertIn('<span aria-hidden="true">P2</span>', punctuation)

    def test_portal_labels_do_not_require_cpython_capitalize(self):
        self.assertEqual(portal_ui.capitalized('aDmInIsTrAtOr'), 'Administrator')
        badge = portal_ui.identity_badge('admin', 'administrator')
        self.assertIn('Administrator privileges', badge)
        restricted = portal_ui.restrict_actions(
            '<form action="/restart-device"><button>Restart</button></form>',
            'viewer'
        )
        self.assertIn('Requires Administrator privileges', restricted)

    def test_render_page_has_auto_refresh_and_scrollable_logs(self):
        status = {
            'device_name': 'Controller', 'mqtt': 'up',
            'config': 'module_settings.ems.json'
        }
        modules = [{
            'uuid': '0001',
            'name': 'Probe',
            'type': 'MAX31865',
            'state': {'temperature': 21},
            'diagnostics': {
                'module_last_ok': True,
                'module_last_read_ms': 12,
                'module_last_publish_age_s': 4,
            },
            'calibratable': True,
            'debug_frames': False,
        }]
        overview = render_page(
            'abc', 'INFO', ('ERROR', 'INFO', 'DEBUG'), ['hello'], 3000,
            status, modules, '', 12000
        )
        logging = web_portal.render_logging_page(
            'abc', 'INFO', ('ERROR', 'INFO', 'DEBUG'), ['hello'], 3000
        )
        diagnostics = web_portal.render_module_diagnostics_page(
            'abc', modules, 3000
        )
        updates = web_portal.render_updates_page(
            'abc', status, {
                'release_channel': 'beta',
                'release_auto_download': True,
                'release_auto_activate': False,
            }
        )

        self.assertIn('<h1>Overview</h1>', overview)
        self.assertIn('Probe', overview)
        self.assertIn('fetch("/api/overview"', overview)
        self.assertNotIn('id="logs"', overview)
        self.assertNotIn('id="update-upload-form"', overview)

        self.assertIn('<h1>Diagnostics</h1>', diagnostics)
        self.assertNotIn('id="logs"', diagnostics)
        self.assertIn('Read duration (ms)', diagnostics)
        self.assertIn('action="/ems-debug"', diagnostics)
        self.assertIn('fetch("/api/module-diagnostics"', diagnostics)

        self.assertIn('<h1>Device log</h1>', logging)
        self.assertIn('id="logs"', logging)
        self.assertIn('hello', logging)
        self.assertIn('name="level"', logging)
        self.assertIn('name="log_buffer_lines"', logging)
        self.assertIn('href="/download-logs"', logging)
        self.assertNotIn('href="/download-diagnostics"', logging)
        self.assertIn('aria-label="Maintenance submenu"', logging)

        self.assertIn('<h1>Upgrades</h1>', updates)
        self.assertIn('<h2>Automatic upgrade</h2>', updates)
        self.assertIn('<h2>Manual upgrade</h2>', updates)
        self.assertLess(
            updates.index('<h2>Automatic upgrade</h2>'),
            updates.index('<h2>Manual upgrade</h2>'),
        )
        self.assertIn('.upgrade-grid{display:grid;grid-template-columns:1fr;', portal_ui.PORTAL_CSS)
        self.assertIn('id="update-upload-form"', updates)
        self.assertIn('Upload and verify', updates)
        self.assertIn('name="release_channel"', updates)
        self.assertIn('id="update-progress"', updates)
        self.assertIn('class="status-spinner"', updates)
        self.assertNotIn('<progress', updates)
        self.assertIn('/resumable-upload-chunk', updates)
        self.assertNotIn('/universal-upload', updates)
        self.assertNotIn('sendUniversal()', updates)
        self.assertIn('kind=universal?"universal"', updates)
        self.assertIn('received_bytes', updates)
        self.assertIn('Writing firmware ', updates)
        self.assertIn('Completed: upload · firmware write', updates)
        self.assertIn('Verification complete', updates)
        self.assertIn('setTimeout(poll,1000)', updates)
        self.assertIn('f.slice(offset,end)', updates)
        self.assertIn('Writing firmware 0%', updates)
        self.assertIn('previous("Completed: upload");startPolling()', updates)
        self.assertNotIn('Writing firmware on device', updates)
        self.assertIn('Verifying application 0%', updates)
        self.assertIn('.hamu', updates)
        self.assertIn('firmware_verification', updates)
        self.assertIn('application_verification', updates)
        self.assertIn('startPolling()', updates)
        self.assertNotIn('Upload complete; verifying', updates)

        settings = render_settings_page('abc', {})
        portal_settings = web_portal.render_portal_settings_page('abc', {})
        self.assertNotIn('name="level"', settings)
        self.assertNotIn('name="loglevel"', settings)
        self.assertNotIn('Change administrator password', settings)
        self.assertIn('name="portal_port"', portal_settings)
        self.assertIn('name="portal_session_timeout_minutes"', portal_settings)
        self.assertIn('value="60"', portal_settings)
        return

        html = render_page(
            'abc',
            'INFO',
            ('ERROR', 'INFO', 'DEBUG'),
            ['hello'],
            3000,
            {'device_name': 'Controller', 'mqtt': 'up', 'config': 'module_settings.ems.json'},
            [{
                'uuid': '0001',
                'name': 'Probe',
                'type': 'MAX31865',
                'state': {'temperature': 21},
                'diagnostics': {'module_last_ok': True, 'module_last_read_ms': 12, 'module_last_publish_age_s': 4},
                'calibratable': True,
                'debug_frames': False
            }],
            '',
            12000
        )
        self.assertIn('id="logs"', html)
        self.assertIn('id="live-sections"', html)
        self.assertIn('HAMD Portal', html)
        self.assertIn('Home Assistant Modular Device', html)
        self.assertEqual(web_portal.render_label('running_version'), 'Application version')
        self.assertEqual(web_portal.render_label('base_version'), 'MicroPython version')
        self.assertIn('Probe', html)
        self.assertIn('Diagnostics', html)
        self.assertIn('Read duration (ms)', html)
        self.assertIn('HA publish age (s)', html)
        self.assertIn('Seconds since state was last published to Home Assistant over MQTT.', html)
        self.assertIn('title="Republish Home Assistant MQTT discovery config for all loaded entities."', html)
        self.assertIn('title="ERROR is quiet, INFO is normal, DEBUG includes MQTT detail."', html)
        self.assertIn('title="Calculate a new in-memory calibration multiplier for this module."', html)
        self.assertIn('action="/ems-debug"', html)
        self.assertIn('Enable debug frames', html)
        self.assertIn('title="Enable or disable verbose EMS UART frame logging."', html)
        self.assertIn('action="/download-logs"', html)
        self.assertIn('Download logs', html)
        self.assertIn(
            'title="Download the current in-memory device log as a text file."',
            html
        )
        self.assertIn('Software update', html)
        self.assertIn('id="update-upload-form"', html)
        self.assertIn('startPolling();return sendChunk', html)
        self.assertIn('Upload and verify', html)
        self.assertIn('application (.hamd) or base firmware (.hamf)', html)
        self.assertNotIn('Application update options:', html)
        self.assertNotIn('action="/activate-update"', html)
        self.assertNotIn('Activate and reboot', html)
        self.assertIn("isFirmware?'/firmware-upload':'/update-upload'", html)

        self.assertIn("request.open('POST',updateUrl,true)", html)
        self.assertIn('request.upload.onprogress=function(progressEvent)', html)
        self.assertIn('request.send(file)', html)
        self.assertIn('id="update-progress-bar"', html)
        self.assertIn('id="update-progress-label"', html)
        self.assertIn("progressLabel.textContent='Uploading '+percent+'%'", html)
        self.assertIn("progressLabel.textContent='Verifying '+percent+'%'", html)
        self.assertIn("state.phase==='verification'", html)
        self.assertIn("fetch('/update-progress?id='", html)
        self.assertNotIn("fetch('/update-progress?token='", html)
        self.assertIn("request.setRequestHeader('X-CSRF-Token',csrfToken)", html)
        self.assertIn("request.setRequestHeader('X-Update-ID',updateId)", html)
        self.assertIn('action="/discover" method="post"', html)
        self.assertIn('scheduleVerificationPoll(500)', html)
        self.assertIn('if(request.status===202)', html)
        self.assertIn("state.phase==='complete'", html)
        self.assertIn("progressLabel.textContent='Verified 100%'", html)
        self.assertIn('request.upload.onload=showVerificationWaiting', html)
        self.assertIn("progressBar.removeAttribute('value')", html)
        self.assertIn("progressLabel.textContent='Verifying...'", html)
        self.assertNotIn('setInterval(pollVerificationProgress', html)
        self.assertIn("progressLabel.textContent='Rejected'", html)
        self.assertIn("progressLabel.textContent='Failed'", html)
        self.assertIn('Upload complete; verifying update...', html)
        self.assertIn('Uploading and verifying base firmware...', html)
        self.assertIn('Uploading and verifying application update...', html)
        self.assertIn('Choose a .hamd or .hamf update bundle.', html)
        self.assertIn('Waiting for current portal request...', html)
        self.assertIn('var refreshInProgress=Promise.resolve()', html)
        self.assertIn('var refreshBusy=false', html)
        self.assertIn('setTimeout(refreshAll,100)', html)
        self.assertIn('refreshInProgress.then(function()', html)
        self.assertIn('},0)', html)
        self.assertNotIn('Uploading and verifying…', html)
        self.assertIn('class="file-input-hidden" type="file"', html)
        self.assertIn('class="file-button" for="update-bundle"', html)
        self.assertIn('input[type="checkbox"]{padding:0', html)
        self.assertIn('uploadInProgress=true', html)
        self.assertIn('setRefreshPaused(true)', html)
        self.assertIn('uploadInProgress=false', html)
        self.assertIn('id="update-file-name"', html)
        self.assertIn("event.target.files[0].name", html)
        self.assertIn('class="log-header-actions"', html)
        self.assertIn('.metric span{white-space:nowrap', html)
        self.assertIn('.metric.wide{grid-column:span 2}', html)
        self.assertIn('class="metric wide"', html)
        self.assertIn('title="module_settings.ems.json"', html)
        self.assertIn('overflow-y:auto', html)
        self.assertIn('requests.push(refreshLogs())', html)
        self.assertIn('requests.push(refreshValues())', html)
        self.assertIn('Promise.all(requests)', html)
        self.assertIn('class="badge good refresh-status"', html)
        self.assertIn('auto refresh', html)

        staged_html = render_page(
            'abc', 'INFO', ('ERROR', 'INFO', 'DEBUG'), [], 3000,
            {
                'running_version': '1.0',
                'base_version': '1.0.0',
                'update_version': '1.1',
                'update_status': 'ready',
                'update_options': ['module_settings', 'certificates'],
                'firmware_update_supported': True,
                'firmware_update_availability': 'ready',
                'firmware_update_status': 'ready',
                'firmware_update_version': 'mp-1.28.0',
                'firmware_running_version': 'mp-1.27.0'
            }, [], '', 12000
        )
        self.assertIn('Application update options:', staged_html)
        self.assertIn('name="module_settings"', staged_html)
        self.assertIn('name="certificates"', staged_html)
        self.assertEqual(staged_html.count('class="update-switch"'), 2)
        self.assertIn('.update-switch input[type="checkbox"]:checked', staged_html)
        self.assertNotIn('name="device_settings"', staged_html)
        self.assertNotIn('name="secrets"', staged_html)
        self.assertIn('action="/activate-update" method="post"', staged_html)
        self.assertIn('Activate and reboot', staged_html)
        self.assertNotIn('Base firmware update', staged_html)
        self.assertNotIn('id="firmware-upload-form"', staged_html)
        self.assertIn('Activate firmware and reboot', staged_html)
        self.assertIn(
            'Application — 1.1 / Core firmware — mp-1.28.0', staged_html
        )
        self.assertIn('<span>OTA firmware availability</span>', staged_html)
        self.assertIn('class="update-summary"', staged_html)
        self.assertIn('metric ota-availability good', staged_html)
        self.assertIn('title="ready">ready</strong>', staged_html)
        self.assertIn('.metric.ota-availability{grid-column:1/-1}', staged_html)
        self.assertIn('.metric.ota-availability strong{white-space:normal', staged_html)
        self.assertIn("isFirmware?'/firmware-upload':'/update-upload'", staged_html)
        app_position = staged_html.index('<span>App version</span>')
        base_position = staged_html.index('<span>MicroPython version</span>')
        staged_position = staged_html.index('<span>Staged update</span>')
        status_position = staged_html.index('<span>Update status</span>')
        software_position = staged_html.index('<h2>Software update</h2>')
        self.assertLess(app_position, base_position)
        self.assertLess(base_position, software_position)
        self.assertLess(software_position, staged_position)
        self.assertLess(staged_position, status_position)
        self.assertNotIn('metric-stack', staged_html)
        self.assertIn('class="metric version-app"', staged_html)
        self.assertIn('class="metric version-base"', staged_html)
        self.assertIn('class="metric update-staged"', staged_html)
        self.assertIn('class="metric update-status"', staged_html)
        self.assertIn('.metric.version-app{grid-column:5;grid-row:2}', staged_html)
        self.assertIn('.metric.version-base{grid-column:6;grid-row:2}', staged_html)
        status_panel = staged_html.split('<h2>Status</h2>', 1)[1].split('</section>', 1)[0]
        self.assertNotIn('Staged update', status_panel)
        self.assertNotIn('Update status', status_panel)
        self.assertNotIn('OTA firmware availability', status_panel)

        firmware_only_html = render_page(
            'abc', 'INFO', ('INFO',), [], 3000,
            {
                'running_version': '1.0',
                'base_version': '1.27.0',
                'update_version': '',
                'update_status': 'idle',
                'firmware_update_supported': True,
                'firmware_update_status': 'ready',
                'firmware_update_version': 'micropython-1.28.0'
            }, [], '', 12000
        )
        self.assertIn(
            '<span>Staged update</span><strong title="Core firmware — micropython-1.28.0">Core firmware — micropython-1.28.0</strong>',
            firmware_only_html
        )
        self.assertIn(
            '<span>Update status</span><strong title="ready">ready</strong>',
            firmware_only_html
        )

        idle_html = web_portal.render_update_summary_html({
            'running_version': '1.0', 'base_version': '1.1.0',
            'update_version': '', 'update_status': 'idle',
            'release_check_status': 'No newer release',
            'release_last_checked': '2026-07-22 05:17:26'
        })
        self.assertIn('id="update-summary"', idle_html)
        self.assertIn('Not staged', idle_html)
        self.assertIn('<span>Last automatic check</span>', idle_html)
        self.assertIn('No newer release — 2026-07-22 05:17:26', idle_html)
        self.assertIn('metric release-check good', idle_html)
        application_only_html = web_portal.render_update_summary_html({
            'update_status': 'ready',
            'update_version': '2.0.0-alpha.8',
            'firmware_update_status': 'idle',
        })
        self.assertIn(
            'Application — 2.0.0-alpha.8', application_only_html
        )
        universal_html = web_portal.render_update_summary_html({
            'update_status': 'ready',
            'update_version': '2.0.0-alpha.8',
            'firmware_update_status': 'ready',
            'firmware_update_version': 'ham-core-2.0.0-alpha.8-mpy1.28.0',
            'universal_update_status': 'ready',
            'universal_update_version': '2.0.0-alpha.8',
        })
        self.assertIn('Universal — 2.0.0-alpha.8', universal_html)
        self.assertNotIn(
            'Application — 2.0.0-alpha.8 / Core firmware', universal_html
        )
        self.assertIn('refresh paused', html)
        self.assertIn('id="refresh-toggle"', html)
        self.assertIn('id="log-refresh-toggle"', html)
        self.assertIn('.refresh-controls{display:grid;grid-template-columns:8rem 5rem;column-gap:.75rem', html)
        self.assertNotIn('>live</span>', html)
        self.assertIn('.refresh-controls .badge,.refresh-toggle{box-sizing:border-box;width:100%}', html)
        self.assertIn('.refresh-status{justify-content:center}', html)
        self.assertIn('.refresh-toggle{text-align:center}', html)
        self.assertIn('>Pause</button>', html)
        self.assertIn("buttons[b].textContent=autoRefreshPaused?'Resume':'Pause'", html)
        self.assertIn("statuses[i].className=autoRefreshPaused?'badge warn refresh-status':'badge good refresh-status'", html)
        self.assertIn('setRefreshPaused(!autoRefreshPaused)', html)
        self.assertIn("event.target.classList.contains('refresh-toggle')", html)
        self.assertIn('updateRefreshControls();', html)
        self.assertIn('refreshTimer=setInterval(refreshAll,Math.min.apply(Math,intervals))', html)
        self.assertIn('var logRefreshMs=3000', html)
        self.assertIn('var valueRefreshMs=12000', html)
        self.assertIn("fetch('/partials',{cache:'no-store',credentials:'same-origin'})", html)
        self.assertIn("if(response.status===401){window.location.replace('/login')", html)
        self.assertIn('authenticatedResponse(r)', html)
        self.assertNotIn('/partials?token=', html)
        self.assertIn('payload.live_sections', html)
        self.assertIn('payload.update_summary', html)
        self.assertIn('payload.update_actions', html)
        self.assertIn("document.getElementById('update-summary')", html)
        self.assertIn("document.getElementById('update-actions')", html)
        self.assertIn('lastValueRefresh=0', html)
        self.assertIn('el.outerHTML=html', html)
        self.assertIn('<pre id="logs">hello</pre>', html)
        self.assertIn("if(request.status===401){window.location.replace('/login')", html)

    def test_upgrade_tiles_keep_each_method_state_aware(self):
        idle = web_portal.render_updates_page('csrf', {
            'release_checks_enabled': True,
            'update_status': 'idle',
            'firmware_update_status': 'idle',
        }, {})
        self.assertIn('<h2>Automatic upgrade</h2>', idle)
        self.assertIn('<h2>Manual upgrade</h2>', idle)
        self.assertIn('action="/check-release"', idle)
        self.assertIn('id="update-upload-form"', idle)
        self.assertIn('Upload and verify', idle)
        self.assertIn('name="release_check_schedule"', idle)
        self.assertIn('<option value="disabled" selected>Disabled</option>', idle)
        self.assertIn('>Daily</option>', idle)
        self.assertIn('>Weekly</option>', idle)
        self.assertIn('name="release_check_time" type="time"', idle)
        self.assertIn('name="release_check_weekday"', idle)
        self.assertIn('id="release-check-fields" class="conditional-fields"', idle)
        self.assertIn('releaseFields.disabled=disabled', idle)
        self.assertIn('syncReleaseSchedule()', idle)

        ready = web_portal.render_updates_page('csrf', {
            'release_checks_enabled': True,
            'update_status': 'ready',
            'firmware_update_status': 'idle',
            'update_options': ('module_settings',),
        }, {})
        self.assertNotIn('id="update-upload-form"', ready)

        universal = web_portal.render_updates_page('csrf', {
            'release_checks_enabled': True,
            'update_status': 'ready',
            'firmware_update_status': 'ready',
            'firmware_update_supported': True,
            'universal_update_status': 'ready',
            'universal_update_version': '2.0.0',
        }, {})
        self.assertIn('action="/activate-universal"', universal)
        self.assertIn('Activate universal update 2.0.0 and reboot', universal)
        self.assertNotIn('action="/activate-update"', universal)
        self.assertNotIn('action="/activate-firmware"', universal)
        self.assertNotIn('Upload and verify', ready)
        self.assertIn('Application uploaded and verified. Ready for activation.', ready)
        self.assertIn('class="task-progress complete"', ready)
        self.assertIn('class="update-actions next-stage"', ready)
        self.assertIn('Activate and reboot', ready)

    def test_make_tls_context_reports_missing_certificate_file(self):
        with self.assertRaisesRegex(RuntimeError, 'certificate file not found'):
            make_tls_context('/tmp/missing-web.crt', '/tmp/missing-web.key')

    def test_make_tls_context_explains_invalid_key(self):
        original_ssl = portal_http.ssl
        original_open = portal_http.open if hasattr(portal_http, 'open') else open

        class FakeContext:
            def load_cert_chain(self, cert_path, key_path):
                raise ValueError('invalid key')

        class FakeSsl:
            PROTOCOL_TLS_SERVER = 1

            def SSLContext(self, protocol):
                return FakeContext()

        try:
            portal_http.ssl = FakeSsl()
            portal_http.open = lambda path, mode='r': original_open(__file__, 'rb')
            with self.assertRaisesRegex(RuntimeError, 'traditional RSA key'):
                make_tls_context('/tmp/web.crt', '/tmp/web.key')
        finally:
            portal_http.ssl = original_ssl
            portal_http.open = original_open


if __name__ == '__main__':
    unittest.main()
