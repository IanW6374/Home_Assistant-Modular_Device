import asyncio
import unittest
from pathlib import Path

import http_support


class HttpSupportTests(unittest.TestCase):
    def test_close_writer_awaits_the_micropython_socket_close(self):
        events = []

        class Writer:
            def close(self):
                events.append('close')

            async def wait_closed(self):
                events.append('wait_closed')

        asyncio.run(http_support.close_writer(Writer()))
        self.assertEqual(events, ['close', 'wait_closed'])

    def test_async_network_services_use_the_common_stream_close(self):
        root = Path(__file__).resolve().parents[1]
        for name in (
            'certificate_manager.py', 'device_api.py', 'release_update.py',
            'remote_logging.py', 'setup_wizard.py', 'web_portal.py',
            'wifi_recovery.py',
        ):
            source = (root / name).read_text()
            self.assertNotIn('writer.close()', source, name)


if __name__ == '__main__':
    unittest.main()
