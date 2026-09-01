import unittest

from feature_flags import FeatureFlags


class FeatureFlagTests(unittest.TestCase):
    def test_core_architecture_flags_default_on(self):
        flags = FeatureFlags()
        self.assertTrue(flags.enabled('transport_independent_api'))
        self.assertTrue(flags.enabled('split_api_payloads'))
        self.assertTrue(flags.enabled('hardware_resource_manager'))

    def test_experimental_transport_requires_policy_capability_and_channel(self):
        capable = {'features': {'usb_ncm': True}}
        self.assertFalse(FeatureFlags(
            {'usb_ncm': True}, capable, 'stable'
        ).enabled('usb_ncm'))
        self.assertFalse(FeatureFlags(
            {'usb_ncm': True}, {'features': {'usb_ncm': False}}, 'beta'
        ).enabled('usb_ncm'))
        self.assertTrue(FeatureFlags(
            {'usb_ncm': True}, capable, 'beta'
        ).enabled('usb_ncm'))

    def test_snapshot_explains_disabled_features(self):
        snapshot = FeatureFlags({'usb_ncm': False}).snapshot()
        state = snapshot['features']['usb_ncm']
        self.assertFalse(state['enabled'])
        self.assertIn('signed application policy', state['reason'])


if __name__ == '__main__':
    unittest.main()
