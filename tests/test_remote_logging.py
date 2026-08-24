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

    def test_system_and_audit_forwarding_are_independent(self):
        audit_only = RemoteSyslog({
            'enabled': False, 'audit_enabled': True,
            'host': 'logs.local', 'port': 514, 'transport': 'udp'
        })

        self.assertFalse(audit_only.enqueue('-', 'system event'))
        self.assertTrue(audit_only.enqueue('-', 'login accepted', audit=True))
        self.assertTrue(audit_only.active)
        self.assertIn(b'HAMD-Audit', audit_only.queue[0])

        system_only = RemoteSyslog({
            'enabled': True, 'audit_enabled': False,
            'host': 'logs.local', 'port': 514, 'transport': 'udp'
        })
        self.assertTrue(system_only.enqueue('-', 'system event'))
        self.assertFalse(system_only.enqueue('-', 'login accepted', audit=True))
        self.assertNotIn(b'HAMD-Audit', system_only.queue[0])

    def test_existing_syslog_configuration_forwards_audit_by_default(self):
        client = RemoteSyslog({
            'enabled': True, 'host': 'logs.local', 'port': 514,
            'transport': 'udp'
        })

        self.assertTrue(client.audit_enabled)
        self.assertTrue(client.enqueue('-', 'legacy audit event', audit=True))


if __name__ == '__main__':
    unittest.main()
