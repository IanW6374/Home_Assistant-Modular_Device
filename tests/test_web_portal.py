import unittest

import web_portal
from web_portal import (
    apply_loglevel_change,
    apply_portal_action,
    is_authenticated,
    is_client_disconnect_error,
    make_tls_context,
    parse_request_line,
    redirect,
    render_log_text,
    render_logs_html,
    render_page,
    requested_loglevel,
    response,
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
        self.assertFalse(is_client_disconnect_error(OSError(12, 'ENOMEM')))

    def test_response_sets_content_length(self):
        raw = response('200 OK', 'hello', 'text/plain')
        self.assertIn('Content-Length: 5', raw)
        self.assertTrue(raw.endswith('\r\n\r\nhello'))

    def test_redirect_sets_location(self):
        raw = redirect('/?token=abc')
        self.assertIn('HTTP/1.1 303 See Other', raw)
        self.assertIn('Location: /?token=abc', raw)

    def test_render_logs_html_escapes_html(self):
        self.assertEqual(render_logs_html(['one < two']), 'one &lt; two')

    def test_render_log_text_does_not_escape_html_entities(self):
        self.assertEqual(render_log_text(['{"state": "ON"}']), '{"state": "ON"}')

    def test_render_page_has_auto_refresh_and_scrollable_logs(self):
        html = render_page(
            'abc',
            'INFO',
            ('ERROR', 'INFO', 'DEBUG'),
            ['hello'],
            3000,
            {'device_name': 'Pico', 'mqtt': 'up'},
            [{
                'uuid': '0001',
                'name': 'Probe',
                'type': 'MAX31865',
                'state': {'temperature': 21},
                'diagnostics': {'module_last_ok': True, 'module_last_read_ms': 12, 'module_last_publish_age_s': 4},
                'calibratable': True
            }],
            '',
            12000
        )
        self.assertIn('id="logs"', html)
        self.assertIn('id="live-sections"', html)
        self.assertIn('Device Portal', html)
        self.assertIn('Probe', html)
        self.assertIn('Diagnostics', html)
        self.assertIn('module last read ms', html)
        self.assertIn('Seconds since this module last published state.', html)
        self.assertIn('title="Republish Home Assistant MQTT discovery config for all loaded entities."', html)
        self.assertIn('title="ERROR is quiet, INFO is normal, DEBUG includes MQTT detail."', html)
        self.assertIn('title="Calculate a new in-memory calibration multiplier for this module."', html)
        self.assertIn('overflow-y:auto', html)
        self.assertIn('refreshLogs();', html)
        self.assertIn('class="badge good refresh-status"', html)
        self.assertIn('class="badge good refresh-placeholder"', html)
        self.assertIn('class="refresh-button-placeholder"', html)
        self.assertIn('auto refresh', html)
        self.assertIn('refresh paused', html)
        self.assertIn('id="refresh-toggle"', html)
        self.assertIn('.refresh-controls{display:grid;grid-template-columns:3.6rem 8rem 5rem;column-gap:.75rem', html)
        self.assertIn('.refresh-controls .badge,#refresh-toggle,.refresh-button-placeholder{box-sizing:border-box;width:100%}', html)
        self.assertIn('.refresh-status{justify-content:center}', html)
        self.assertIn('.refresh-placeholder,.refresh-button-placeholder{visibility:hidden}', html)
        self.assertIn('#refresh-toggle{text-align:center}', html)
        self.assertIn('>Pause</button>', html)
        self.assertIn("button.textContent=autoRefreshPaused?'Resume':'Pause'", html)
        self.assertIn("statuses[i].className=autoRefreshPaused?'badge warn refresh-status':'badge good refresh-status'", html)
        self.assertIn('setRefreshPaused(!autoRefreshPaused)', html)
        self.assertIn("event.target&&event.target.id==='refresh-toggle'", html)
        self.assertIn('updateRefreshControls();', html)
        self.assertIn('logRefreshTimer=setInterval(refreshLogs,logRefreshMs)', html)
        self.assertIn('var logRefreshMs=3000', html)
        self.assertIn('var valueRefreshMs=12000', html)
        self.assertIn("fetch('/partials?token='+encodeURIComponent(token)", html)
        self.assertIn('valueRefreshTimer=setInterval(refreshValues,valueRefreshMs)', html)
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
