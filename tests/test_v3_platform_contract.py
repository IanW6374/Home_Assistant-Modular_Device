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
            ABI_VERSION = 4

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

            def update_snapshot(self):
                return {
                    'running_label': 'ota_1', 'running_state': 'valid',
                    'next_label': 'ota_0', 'pending_verify': False,
                    'can_confirm': False, 'can_rollback': False,
                }

            def update_confirm(self, expected):
                return True

            def update_rollback(self, expected):
                return None

            def recovery_boot_begin(self): return 0
            def recovery_snapshot(self):
                return {
                    'requested': False, 'reason': '', 'boot_pending': False,
                    'boot_count': 1, 'failed_boots': 0, 'reset_reason': 1,
                }
            def recovery_request(self, reason): return True
            def recovery_mark_healthy(self): return True
            def recovery_clear(self): return True
            def job_submit(self, kind, argument): return 1
            def event_poll(self): return None

            def capabilities(self):
                return V3PlatformContractTests().example()

        platform = Platform(Provider())
        self.assertEqual(platform.capabilities()['abi_version'], 4)
        self.assertEqual(platform.update_snapshot()['running_label'], 'ota_1')
        Provider.ABI_VERSION = 3
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
            ABI_VERSION = 4

            def capabilities(self):
                return V3PlatformContractTests().example()

        with self.assertRaisesRegex(PlatformContractError, 'storage'):
            Platform(Provider())

    def test_native_rollback_requires_paired_trial(self):
        value = self.example()
        value['updates']['native_rollback'] = True
        with self.assertRaisesRegex(PlatformContractError, 'rollback'):
            validate_capabilities(value)

    def test_native_trial_control_requires_observation(self):
        value = self.example()
        value['updates']['native_trial_observation'] = False
        with self.assertRaisesRegex(PlatformContractError, 'observation'):
            validate_capabilities(value)

    def test_native_job_deadline_is_bounded(self):
        value = self.example()
        value['jobs']['timeout_ms'] = 0
        with self.assertRaisesRegex(PlatformContractError, 'timeout'):
            validate_capabilities(value)

    def test_native_update_snapshot_fails_closed_on_inconsistent_state(self):
        class Provider:
            ABI_VERSION = 4

            def capabilities(self):
                return V3PlatformContractTests().example()

            def storage_open(self, namespace): return 1
            def storage_close(self, handle): return None
            def storage_snapshot(self, handle):
                return {'generation': 0, 'payload': b''}
            def storage_commit(self, handle, generation, payload): return 1
            def resource_claim(self, kind, identifier, owner): return 1
            def resource_release(self, handle): return None
            def resource_release_owner(self, owner): return 0
            def resource_snapshot(self): return []
            def update_snapshot(self):
                return {
                    'running_label': 'ota_0', 'running_state': 'valid',
                    'next_label': 'ota_1', 'pending_verify': False,
                    'can_confirm': True, 'can_rollback': False,
                }
            def update_confirm(self, expected): return True
            def update_rollback(self, expected): return None
            def recovery_boot_begin(self): return 0
            def recovery_snapshot(self):
                return {
                    'requested': False, 'reason': '', 'boot_pending': False,
                    'boot_count': 1, 'failed_boots': 0, 'reset_reason': 1,
                }
            def recovery_request(self, reason): return True
            def recovery_mark_healthy(self): return True
            def recovery_clear(self): return True
            def job_submit(self, kind, argument): return 1
            def event_poll(self): return None

        with self.assertRaisesRegex(PlatformContractError, 'confirm state'):
            Platform(Provider()).update_snapshot()

    def test_recovery_and_native_jobs_are_bounded(self):
        class Provider:
            ABI_VERSION = 4
            def capabilities(self): return V3PlatformContractTests().example()
            def storage_open(self, namespace): return 1
            def storage_close(self, handle): return None
            def storage_snapshot(self, handle): return {'generation': 0, 'payload': b''}
            def storage_commit(self, handle, generation, payload): return 1
            def resource_claim(self, kind, identifier, owner): return 1
            def resource_release(self, handle): return None
            def resource_release_owner(self, owner): return 0
            def resource_snapshot(self): return []
            def update_snapshot(self):
                return {'running_label': 'ota_0', 'running_state': 'valid',
                        'next_label': 'ota_1', 'pending_verify': False,
                        'can_confirm': False, 'can_rollback': False}
            def update_confirm(self, expected): return True
            def update_rollback(self, expected): return None
            def recovery_boot_begin(self): return 2
            def recovery_snapshot(self):
                return {'requested': True, 'reason': 'test',
                        'boot_pending': True, 'boot_count': 4,
                        'failed_boots': 2, 'reset_reason': 3}
            def recovery_request(self, reason): return True
            def recovery_mark_healthy(self): return True
            def recovery_clear(self): return True
            def job_submit(self, kind, argument): return 7
            def event_poll(self):
                return {'id': 7, 'kind': 'recovery-request',
                        'status': 'completed', 'error': 0,
                        'retryable': False,
                        'detail': 'native recovery requested'}

        platform = Platform(Provider())
        self.assertEqual(platform.recovery_boot_begin(), 2)
        self.assertTrue(platform.recovery_snapshot()['requested'])
        self.assertEqual(platform.submit_job('recovery-request', 'test'), 7)
        event = platform.poll_event()
        self.assertEqual(event['status'], 'completed')
        self.assertFalse(event['retryable'])


if __name__ == '__main__':
    unittest.main()
