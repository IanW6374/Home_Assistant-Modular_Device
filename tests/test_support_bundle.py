import unittest

import support_bundle


class FakeHealth:
    def snapshot(self):
        return {'events': [{'kind': 'boot'}], 'private_key': 'must not leak'}


class SupportBundleTests(unittest.TestCase):
    def test_bundle_omits_secret_named_fields_and_bounds_logs(self):
        result = support_bundle.build_support_bundle(
            {'device_name': 'test', 'wifi_password': 'secret'}, FakeHealth(),
            modules=[{'name': 'sensor', 'api_token': 'secret'}],
            logs=['x' * 1000],
        )

        self.assertEqual(result['device'], {'device_name': 'test'})
        self.assertEqual(result['modules'], [{'name': 'sensor'}])
        self.assertNotIn('private_key', result['health'])
        self.assertEqual(len(result['logs'][0]), 512)


if __name__ == '__main__':
    unittest.main()
