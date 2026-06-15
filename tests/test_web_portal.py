import unittest

from web_portal import (
    is_authenticated,
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
        html = render_page('abc', 'INFO', ('ERROR', 'INFO', 'DEBUG'), ['hello'], 3000)
        self.assertIn('id="logs"', html)
        self.assertIn('overflow-y:auto', html)
        self.assertIn('refreshLogs();', html)
        self.assertIn('setInterval(refreshLogs,refreshMs)', html)
        self.assertIn('var refreshMs=3000', html)
        self.assertNotIn('hello', html)


if __name__ == '__main__':
    unittest.main()
