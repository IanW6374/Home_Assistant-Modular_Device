import unittest

from remote_logging import RemoteSyslog, rfc5424_message


class RemoteLoggingTests(unittest.TestCase):
    def test_rfc5424_message_uses_local0_and_expected_severity(self):
        payload = rfc5424_message(
            '2026-08-22T12:00:00', 'controller', 'IoTMD', 'Started', 'ERROR'
        ).decode()

        self.assertTrue(payload.startswith('<131>1 2026-08-22T12:00:00Z controller IoTMD'))
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
        self.assertIn(b'IoTMD-Audit', audit_only.queue[0])

        system_only = RemoteSyslog({
            'enabled': True, 'audit_enabled': False,
            'host': 'logs.local', 'port': 514, 'transport': 'udp'
        })
        self.assertTrue(system_only.enqueue('-', 'system event'))
        self.assertFalse(system_only.enqueue('-', 'login accepted', audit=True))
        self.assertNotIn(b'IoTMD-Audit', system_only.queue[0])

    def test_existing_syslog_configuration_forwards_audit_by_default(self):
        client = RemoteSyslog({
            'enabled': True, 'host': 'logs.local', 'port': 514,
            'transport': 'udp'
        })

        self.assertTrue(client.audit_enabled)
        self.assertTrue(client.enqueue('-', 'legacy audit event', audit=True))

    def test_delivery_failures_are_visible_and_recovery_is_reported_once(self):
        notices = []
        client = RemoteSyslog(
            {'enabled': True, 'host': 'logs.local', 'transport': 'tls'},
            status_callback=lambda severity, message: notices.append(
                (severity, message)
            )
        )

        client._delivery_failed(OSError('connection refused'))
        client._delivery_failed(OSError('connection refused'))
        self.assertEqual(client.status()['failures'], 2)
        self.assertEqual(client.status()['consecutive_failures'], 2)
        self.assertEqual(len(notices), 1)
        self.assertIn('connection refused', notices[0][1])

        client._delivery_succeeded()
        client._delivery_succeeded()
        self.assertEqual(client.status()['delivered'], 2)
        self.assertEqual(client.status()['consecutive_failures'], 0)
        self.assertEqual(len(notices), 2)
        self.assertIn('recovered after 2 failures', notices[1][1])


if __name__ == '__main__':
    unittest.main()
