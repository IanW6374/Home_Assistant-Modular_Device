import asyncio
import unittest

import credential_store
import portal_auth


class PortalAuthTests(unittest.TestCase):
    def setUp(self):
        credential_store._memory_values.clear()
        config = credential_store.build_configuration({
            'device_name': 'Controller', 'wifi_ssid': 'network',
            'wifi_password': 'network-password', 'mqtt_server': 'mqtt.local',
            'mqtt_port': 8883, 'mqtt_ssl': True, 'portal_username': 'admin',
            'recovery_ap_password': 'Recovery-Access-47!River',
            'channel': 'stable',
        }, 'Administrator-Cedar-47!River', 'Recovery-Console-82!Stone')
        config['provisioned'] = True
        credential_store.save(config)

    def tearDown(self):
        credential_store._memory_values.clear()

    def test_add_authenticate_update_and_remove_user(self):
        portal_auth.add_user('viewer', 'Viewer-Cedar-47!River', 'viewer')
        identity = asyncio.run(portal_auth.authenticate(
            'viewer', 'Viewer-Cedar-47!River'
        ))
        self.assertEqual(identity, {'username': 'viewer', 'role': 'viewer'})

        portal_auth.update_user('viewer', role='operator', enabled=False)
        self.assertIsNone(asyncio.run(portal_auth.authenticate(
            'viewer', 'Viewer-Cedar-47!River'
        )))
        self.assertTrue(portal_auth.remove_user('viewer'))

    def test_cannot_remove_or_disable_last_administrator(self):
        with self.assertRaisesRegex(ValueError, 'administrator'):
            portal_auth.update_user('admin', enabled=False)
        with self.assertRaisesRegex(ValueError, 'administrator'):
            portal_auth.remove_user('admin')

    def test_route_roles(self):
        self.assertEqual(portal_auth.required_role('GET', '/'), 'viewer')
        self.assertEqual(portal_auth.required_role('POST', '/activate-update'), 'operator')
        self.assertEqual(portal_auth.required_role('GET', '/certificates'), 'administrator')
        self.assertEqual(portal_auth.required_role('GET', '/api/restart-required'), 'viewer')
        self.assertEqual(portal_auth.required_role('POST', '/restart-device'), 'administrator')
        self.assertTrue(portal_auth.role_allows('administrator', 'operator'))
        self.assertFalse(portal_auth.role_allows('viewer', 'operator'))


if __name__ == '__main__':
    unittest.main()
