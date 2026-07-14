import unittest
import asyncio

import web_portal
from web_portal import (
    apply_loglevel_change,
    apply_portal_action,
    download_response,
    encoded_length,
    friendly_label,
    is_authenticated,
    is_client_disconnect_error,
    make_tls_context,
    parse_request_line,
    redirect,
    render_log_text,
    render_logs_html,
    render_page,
    render_page_parts,
    requested_loglevel,
    response,
    write_streamed_response,
    write_streamed_parts,
)


class WebPortalTests(unittest.TestCase):
    def test_request_line_parsing(self):
        self.assertEqual(
            parse_request_line('GET /?token=abc HTTP/1.1'),
            ('GET', '/?token=abc')
        )

    def test_token_authentication(self):
        self.assertTrue(is_authenticated('/?token=abc123', 'abc123'))
        self.assertFalse(is_authenticated('/?token=wrong', 'abc123'))
        self.assertFalse(is_authenticated('/?token=abc123', ''))

    def test_requested_loglevel_must_be_allowed(self):
        levels = ('ERROR', 'INFO', 'DEBUG')
        self.assertEqual(requested_loglevel('/set-loglevel?level=debug&token=abc', levels), 'DEBUG')
        self.assertIsNone(requested_loglevel('/set-loglevel?level=TRACE&token=abc', levels))

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

    def test_apply_portal_action_logs_action_result_once(self):
        actions = []
        logs = []

        result = apply_portal_action(
            'calibrate',
            '/calibrate?token=abc&uuid=0001&known_voltage=240',
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
        self.assertFalse(is_client_disconnect_error(OSError(12, 'ENOMEM')))

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

    def test_streamed_response_writes_body_in_small_chunks(self):
        class Writer:
            def __init__(self):
                self.chunks = []

            def write(self, data):
                self.chunks.append(data)

            async def drain(self):
                return

        writer = Writer()
        body = '£' * 2000

        asyncio.run(write_streamed_response(
            writer,
            '200 OK',
            body,
            'text/plain',
            chunk_size=128
        ))

        raw = b''.join(writer.chunks)
        headers, payload = raw.split(b'\r\n\r\n', 1)
        self.assertIn(
            ('Content-Length: ' + str(encoded_length(body, 128))).encode(),
            headers
        )
        self.assertEqual(payload.decode(), body)
        self.assertLessEqual(max(len(chunk) for chunk in writer.chunks[1:]), 256)

    def test_page_fragments_stream_without_constructing_full_response(self):
        parts = render_page_parts(
            'abc', 'INFO', ('ERROR', 'INFO', 'DEBUG'), [], 3000,
            {'device_name': 'Pico 2 W'}, [], '', 12000
        )
        self.assertGreater(len(parts), 5)
        self.assertLess(max(len(part) for part in parts), 6000)
        self.assertEqual(
            ''.join(parts),
            render_page(
                'abc', 'INFO', ('ERROR', 'INFO', 'DEBUG'), [], 3000,
                {'device_name': 'Pico 2 W'}, [], '', 12000
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
        raw = redirect('/?token=abc')
        self.assertIn('HTTP/1.1 303 See Other', raw)
        self.assertIn('Location: /?token=abc', raw)

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

    def test_render_page_has_auto_refresh_and_scrollable_logs(self):
        html = render_page(
            'abc',
            'INFO',
            ('ERROR', 'INFO', 'DEBUG'),
            ['hello'],
            3000,
            {'device_name': 'Pico', 'mqtt': 'up', 'config': 'module_settings_EMS.json'},
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
        self.assertIn('Device Portal', html)
        self.assertEqual(web_portal.render_label('running_version'), 'App version')
        self.assertEqual(web_portal.render_label('base_version'), 'Base version')
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
        self.assertIn('Application update', html)
        self.assertIn('id="update-upload-form"', html)
        self.assertIn('Upload and stage', html)
        self.assertNotIn('Optional overwrite:', html)
        self.assertNotIn('action="/activate-update"', html)
        self.assertNotIn('Activate and reboot', html)
        self.assertIn("var updateUrl='/update-upload?token='", html)
        self.assertIn('fetch(updateUrl,{', html)
        self.assertIn('Uploading and verifying...', html)
        self.assertIn('Waiting for current portal request...', html)
        self.assertIn('var refreshInProgress=Promise.resolve()', html)
        self.assertIn('var refreshBusy=false', html)
        self.assertIn('setTimeout(refreshAll,1200)', html)
        self.assertIn('refreshInProgress.then(function()', html)
        self.assertIn('},400)', html)
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
        self.assertIn('title="module_settings_EMS.json"', html)
        self.assertIn('overflow-y:auto', html)
        self.assertIn('chain=chain.then(refreshLogs)', html)
        self.assertIn('if(refreshedLogs){chain=chain.then(settleConnection);}', html)
        self.assertIn('chain=chain.then(refreshValues)', html)
        self.assertIn('class="badge good refresh-status"', html)
        self.assertIn('auto refresh', html)

        staged_html = render_page(
            'abc', 'INFO', ('ERROR', 'INFO', 'DEBUG'), [], 3000,
            {
                'running_version': '1.0',
                'base_version': '1.0.0',
                'update_version': '1.1',
                'update_status': 'ready',
                'update_options': ['device_settings', 'certificates'],
                'firmware_update_supported': True,
                'firmware_update_status': 'ready',
                'firmware_update_version': 'mp-1.28.0',
                'firmware_running_version': 'mp-1.27.0'
            }, [], '', 12000
        )
        self.assertIn('Optional overwrite:', staged_html)
        self.assertIn('name="device_settings"', staged_html)
        self.assertIn('name="certificates"', staged_html)
        self.assertNotIn('name="module_settings"', staged_html)
        self.assertNotIn('name="secrets"', staged_html)
        self.assertIn('action="/activate-update"', staged_html)
        self.assertIn('Activate and reboot', staged_html)
        self.assertIn('Base firmware update', staged_html)
        self.assertIn('id="firmware-upload-form"', staged_html)
        self.assertIn('Running firmware: <strong>mp-1.27.0</strong>', staged_html)
        self.assertIn('accept=".hamf,application/octet-stream"', staged_html)
        self.assertIn('Activate firmware and reboot', staged_html)
        self.assertIn("fetch('/firmware-upload?token='", staged_html)
        app_position = staged_html.index('<span>App version</span>')
        base_position = staged_html.index('<span>Base version</span>')
        staged_position = staged_html.index('<span>Staged version</span>')
        status_position = staged_html.index('<span>Update status</span>')
        self.assertLess(app_position, base_position)
        self.assertLess(base_position, staged_position)
        self.assertLess(staged_position, status_position)
        self.assertNotIn('metric-stack', staged_html)
        self.assertIn('class="metric version-app"', staged_html)
        self.assertIn('class="metric version-base"', staged_html)
        self.assertIn('class="metric version-staged"', staged_html)
        self.assertIn('class="metric version-status"', staged_html)
        self.assertIn('.metric.version-app{grid-column:5;grid-row:2}', staged_html)
        self.assertIn('.metric.version-base{grid-column:6;grid-row:2}', staged_html)
        self.assertIn('.metric.version-staged{grid-column:5;grid-row:3}', staged_html)
        self.assertIn('.metric.version-status{grid-column:6;grid-row:3}', staged_html)

        idle_html = web_portal.render_status_html({
            'running_version': '1.0', 'base_version': '1.1.0',
            'update_version': '', 'update_status': 'idle'
        })
        self.assertIn('Not staged', idle_html)
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
        self.assertIn("fetch('/partials?token='+encodeURIComponent(token)", html)
        self.assertIn('lastValueRefresh=0', html)
        self.assertIn('el.outerHTML=html', html)
        self.assertNotIn('hello', html)

    def test_make_tls_context_reports_missing_certificate_file(self):
        with self.assertRaisesRegex(RuntimeError, 'certificate file not found'):
            make_tls_context('/tmp/missing-web.crt', '/tmp/missing-web.key')

    def test_make_tls_context_explains_invalid_key(self):
        original_ssl = web_portal.ssl
        original_open = web_portal.open if hasattr(web_portal, 'open') else open

        class FakeContext:
            def load_cert_chain(self, cert_path, key_path):
                raise ValueError('invalid key')

        class FakeSsl:
            PROTOCOL_TLS_SERVER = 1

            def SSLContext(self, protocol):
                return FakeContext()

        try:
            web_portal.ssl = FakeSsl()
            web_portal.open = lambda path, mode='r': original_open(__file__, 'rb')
            with self.assertRaisesRegex(RuntimeError, 'traditional RSA key'):
                make_tls_context('/tmp/web.crt', '/tmp/web.key')
        finally:
            web_portal.ssl = original_ssl
            web_portal.open = original_open


if __name__ == '__main__':
    unittest.main()
