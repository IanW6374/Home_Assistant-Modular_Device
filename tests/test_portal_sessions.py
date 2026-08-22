import unittest

from portal_sessions import PortalSessions


class PortalSessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.counter = 0

        def token():
            self.counter += 1
            return 'token-' + str(self.counter)

        self.sessions = PortalSessions(
            token, lambda: self.now, timeout_ms=100, maximum=2
        )

    def test_sessions_are_independent_and_csrf_is_not_cookie(self):
        first = self.sessions.create({'username': 'one', 'role': 'viewer'})
        second = self.sessions.create({'username': 'two', 'role': 'operator'})
        self.assertNotEqual(first['id'], first['csrf'])
        self.assertEqual(self.sessions.get(first['id'])['username'], 'one')
        self.assertEqual(self.sessions.get(second['id'])['username'], 'two')
        self.assertTrue(self.sessions.verify_csrf(first['id'], first['csrf']))
        self.assertFalse(self.sessions.verify_csrf(first['id'], second['csrf']))

    def test_expiry_eviction_and_user_revocation(self):
        first = self.sessions.create({'username': 'one', 'role': 'viewer'})
        self.sessions.create({'username': 'two', 'role': 'viewer'})
        self.sessions.create({'username': 'three', 'role': 'viewer'})
        self.assertIsNone(self.sessions.get(first['id']))
        self.assertEqual(self.sessions.revoke_user('two'), 1)
        self.now += 101
        self.assertEqual(self.sessions.count(), 0)


if __name__ == '__main__':
    unittest.main()
