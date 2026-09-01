import asyncio
import unittest

from tls_sessions import TLSSessionHandle, open_tls_connection


class TLSSessionTests(unittest.TestCase):
    def test_v129_compatible_open_ignores_opaque_session(self):
        class AsyncIO:
            calls = []

            @classmethod
            async def open_connection(cls, host, port, **kwargs):
                cls.calls.append((host, port, kwargs))
                return 'reader', 'writer'

        session = TLSSessionHandle(object(), supported=True)
        result = asyncio.run(open_tls_connection(
            AsyncIO, 'service.local', 443, 'context', 'service.local', session
        ))
        self.assertEqual(result, ('reader', 'writer'))
        self.assertNotIn('session', AsyncIO.calls[0][2])
        self.assertEqual(AsyncIO.calls[0][2]['server_hostname'], 'service.local')

    def test_handle_can_be_invalidated_without_exposing_native_value(self):
        handle = TLSSessionHandle(object(), supported=True)
        self.assertTrue(handle.supported)
        self.assertFalse(hasattr(handle, 'native'))
        handle.clear()
        self.assertFalse(handle.supported)


if __name__ == '__main__':
    unittest.main()
