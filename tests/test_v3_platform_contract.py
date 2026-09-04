import json
from pathlib import Path
import unittest

from v3.runtime.iotmd_next.platform import (
    Platform, PlatformContractError, validate_capabilities,
)


ROOT = Path(__file__).resolve().parents[1]


class V3PlatformContractTests(unittest.TestCase):
    def example(self):
        path = (
            ROOT / 'v3' / 'contracts' / 'examples' /
            'platform-capabilities.json'
        )
        return json.loads(path.read_text())

    def test_checked_in_example_is_accepted_by_runtime_adapter(self):
        value = self.example()
        self.assertIs(validate_capabilities(value), value)

    def test_provider_must_match_versioned_native_abi(self):
        class Provider:
            ABI_VERSION = 3

            def storage_open(self, namespace):
                return 1

            def storage_close(self, handle):
                return None

            def storage_snapshot(self, handle):
                return {'generation': 0, 'payload': b''}

            def storage_commit(self, handle, generation, payload):
                return generation + 1

            def resource_claim(self, kind, identifier, owner):
                return 1

            def resource_release(self, handle):
                return None

            def resource_release_owner(self, owner):
                return 0

            def resource_snapshot(self):
                return []

            def capabilities(self):
                return V3PlatformContractTests().example()

        self.assertEqual(Platform(Provider()).capabilities()['abi_version'], 3)
        Provider.ABI_VERSION = 2
        with self.assertRaisesRegex(PlatformContractError, 'ABI'):
            Platform(Provider())

    def test_available_ncm_requires_every_lower_platform_gate(self):
        value = self.example()
        value['interfaces']['usb_ncm_available'] = True
        with self.assertRaisesRegex(PlatformContractError, 'NCM'):
            validate_capabilities(value)

    def test_unknown_native_fields_fail_closed(self):
        value = self.example()
        value['native_pointer'] = 1234
        with self.assertRaisesRegex(PlatformContractError, 'unknown'):
            validate_capabilities(value)

    def test_native_storage_must_be_complete(self):
        class Provider:
            ABI_VERSION = 3

            def capabilities(self):
                return V3PlatformContractTests().example()

        with self.assertRaisesRegex(PlatformContractError, 'storage'):
            Platform(Provider())

    def test_native_rollback_requires_paired_trial(self):
        value = self.example()
        value['updates']['native_rollback'] = True
        with self.assertRaisesRegex(PlatformContractError, 'rollback'):
            validate_capabilities(value)


if __name__ == '__main__':
    unittest.main()
