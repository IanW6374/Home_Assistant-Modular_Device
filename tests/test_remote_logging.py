import unittest

from remote_logging import RemoteSyslog, rfc5424_message


class RemoteLoggingTests(unittest.TestCase):
    def test_rfc5424_message_uses_local0_and_expected_severity(self):
        payload = rfc5424_message(
            '2026-08-22T12:00:00', 'controller', 'HAMD', 'Started', 'ERROR'
        ).decode()

        self.assertTrue(payload.startswith('<131>1 2026-08-22T12:00:00Z controller HAMD'))
        self.assertTrue(payload.endswith(' Started'))

    def test_remote_queue_is_bounded_and_counts_drops(self):
        client = RemoteSyslog(
            {'enabled': True, 'host': 'logs.local', 'port': 514, 'transport': 'udp'},
            queue_limit=2
        )

        client.enqueue('-', 'one')
        client.enqueue('-', 'two')
        client.enqueue('-', 'three')

        self.assertEqual(len(client.queue), 2)
        self.assertEqual(client.dropped, 1)
        self.assertNotIn(b'one', client.queue[0])


if __name__ == '__main__':
    unittest.main()
