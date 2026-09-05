import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import recovery_boot
import credential_store
import boot_state


class RecoveryBootTests(unittest.TestCase):
    def test_user_visible_access_point_names_use_iotmd_brand(self):
        self.assertTrue(recovery_boot._setup_ap_name().startswith('IoT-MD-Setup-'))
        self.assertTrue(recovery_boot._recovery_ap_name().startswith('IoT-MD-Recovery-'))

    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)
        recovery_boot._trial_timer = None
        boot_state.reset_store()
        credential_store._reset_memory_backend()
        boot_state.reset_store()
        config = credential_store.build_configuration({
            'device_name': 'Controller', 'wifi_ssid': 'network',
            'wifi_password': 'wifi-password', 'mqtt_server': 'mqtt.local',
            'mqtt_port': '8883', 'mqtt_username': '', 'mqtt_password': '',
            'mqtt_ssl': True, 'portal_username': 'admin',
            'recovery_ap_password': 'Recovery-Access-Cedar-47!',
            'profile': 'whes', 'channel': 'stable',
        }, 'Portal-Cedar-47!River', 'Console-Ash-82!Stone')
        credential_store.mark_provisioned(config)

    def tearDown(self):
        os.chdir(self.previous_cwd)
        credential_store._reset_memory_backend()
        self.temp.cleanup()

    def fake_modules(self, source, app_status='trial', firmware_status='idle'):
        Path('entry.py').write_text(source)
        values = {
            'app_status': app_status,
            'app_rollbacks': 0,
            'prepared': 0,
            'firmware_boots': 0,
        }

        def app_update_status():
            return {'status': values['app_status']}

        def confirm_update():
            values['app_status'] = 'idle'
            return True

        def rollback_update():
            values['app_rollbacks'] += 1
            values['app_status'] = 'idle'
            return True

        def prepare_application_path():
            values['prepared'] += 1
            return '.app-slots/a'

        app = SimpleNamespace(
            activate_pending=lambda: '',
            rollback_update=rollback_update,
            prepare_application_path=prepare_application_path,
            application_entry=lambda: 'entry.py',
            update_status=app_update_status,
            confirm_update=confirm_update,
        )

        def firmware_boot_status():
            values['firmware_boots'] += 1

        firmware = SimpleNamespace(
            boot_status=firmware_boot_status,
            update_status=lambda: {'status': firmware_status},
        )
        return values, app, firmware

    def test_runs_selected_application_and_accepts_health_confirmation(self):
        values, app, firmware = self.fake_modules(
            'import app_update\n'
            'import recovery_boot\n'
            'app_update.confirm_update()\n'
            'recovery_boot.mark_application_healthy()\n'
            'with open("ran", "w") as output:\n'
            '    output.write("yes")\n'
        )

        with patch.dict(sys.modules, {
            'app_update': app,
            'firmware_update': firmware,
        }), patch.object(recovery_boot, '_reset') as reset:
            recovery_boot.run()

        self.assertEqual(Path('ran').read_text(), 'yes')
        self.assertEqual(values['firmware_boots'], 1)
        self.assertEqual(values['prepared'], 1)
        self.assertEqual(values['app_rollbacks'], 0)
        # The real application runs forever; returning after confirmation is
        # still treated as an abnormal exit and enters recovery on next boot.
        reset.assert_called_once_with()
        self.assertEqual(recovery_boot._read_recovery_state()['mode'], 'recovery')

    def test_normal_return_without_confirmation_rolls_back_and_resets(self):
        values, app, firmware = self.fake_modules('VALUE = 1\n')

        with patch.dict(sys.modules, {
            'app_update': app,
            'firmware_update': firmware,
        }), patch.object(recovery_boot, '_reset') as reset:
            recovery_boot.run()

        self.assertEqual(values['app_rollbacks'], 1)
        reset.assert_called_once_with()

    def test_application_exception_rolls_back_trial_before_reset(self):
        values, app, firmware = self.fake_modules(
            'raise RuntimeError("broken trial")\n'
        )

        with patch.dict(sys.modules, {
            'app_update': app,
            'firmware_update': firmware,
        }), patch.object(recovery_boot, '_reset') as reset:
            recovery_boot.run()

        self.assertEqual(values['app_rollbacks'], 1)
        reset.assert_called_once_with()
        import update_support
        failures = [
            item for item in update_support.update_history()
            if item.get('event') == 'startup_failed'
        ]
        self.assertEqual(failures[-1]['kind'], 'application')
        self.assertIn('broken trial', failures[-1]['detail'])

    def test_application_exception_records_loader_heap_diagnostics(self):
        values, app, firmware = self.fake_modules(
            'raise MemoryError("import heap exhausted")\n'
        )
        snapshots = [
            {'free': 131072, 'allocated': 524288},
            {'free': 98304, 'allocated': 557056},
        ]

        with patch.dict(sys.modules, {
            'app_update': app,
            'firmware_update': firmware,
        }), patch.object(
            recovery_boot, '_heap_snapshot', side_effect=snapshots
        ), patch.object(recovery_boot, '_reset'):
            recovery_boot.run()

        import update_support
        failures = [
            item for item in update_support.update_history()
            if item.get('event') == 'startup_failed'
        ]
        detail = failures[-1]['detail']
        self.assertIn('import heap exhausted', detail)
        self.assertIn('heap before load free=131072 allocated=524288', detail)
        self.assertIn('before execute free=98304 allocated=557056', detail)

    def test_confirmed_application_exception_requests_core_recovery(self):
        values, app, firmware = self.fake_modules(
            'raise RuntimeError("broken confirmed app")\n', app_status='idle'
        )

        with patch.dict(sys.modules, {
            'app_update': app,
            'firmware_update': firmware,
        }), patch.object(recovery_boot, '_reset') as reset:
            recovery_boot.run()

        state = recovery_boot._read_recovery_state()
        self.assertEqual(state['mode'], 'recovery')
        self.assertIn('broken confirmed app', state['reason'])
        reset.assert_called_once_with()

    def test_requested_recovery_starts_before_application(self):
        values, app, firmware = self.fake_modules(
            'raise AssertionError("application must not run")\n', app_status='idle'
        )
        recovery_boot.request_recovery('manual recovery test')

        with patch.dict(sys.modules, {
            'app_update': app,
            'firmware_update': firmware,
        }), patch.object(recovery_boot, '_run_core_recovery') as recovery:
            recovery_boot.run()

        recovery.assert_called_once_with('manual recovery test')
        self.assertEqual(values['prepared'], 0)

    def test_native_recovery_request_is_honoured_before_product_load(self):
        class Native:
            ABI_VERSION = 4
            def recovery_boot_begin(self): return 1
            def recovery_snapshot(self):
                return {'requested': True, 'reason': 'native watchdog loop'}

        values, app, firmware = self.fake_modules(
            'raise AssertionError("application must not run")\n',
            app_status='idle'
        )
        with patch.dict(sys.modules, {
            'app_update': app, 'firmware_update': firmware,
        }), patch.object(
            recovery_boot, '_native_platform', return_value=Native()
        ), patch.object(recovery_boot, '_run_core_recovery') as recovery:
            recovery_boot.run()

        recovery.assert_called_once_with('native watchdog loop')
        self.assertEqual(values['prepared'], 0)

    def test_native_failed_boot_threshold_requests_recovery(self):
        class Native:
            ABI_VERSION = 4
            def __init__(self): self.reasons = []
            def recovery_boot_begin(self): return 3
            def recovery_snapshot(self): return {'requested': False}
            def recovery_request(self, reason): self.reasons.append(reason)

        native = Native()
        with patch.object(recovery_boot, '_native_platform', return_value=native):
            reason = recovery_boot._begin_native_recovery_state()
        self.assertIn('after 3 boots', reason)
        self.assertEqual(native.reasons, [reason])

    def test_unprovisioned_device_starts_first_boot_wizard(self):
        values, app, firmware = self.fake_modules(
            'raise AssertionError("application must not run")\n', app_status='idle'
        )
        credential_store._reset_memory_backend()
        with patch.dict(sys.modules, {
            'app_update': app,
            'firmware_update': firmware,
        }), patch.object(recovery_boot, '_run_initial_setup') as setup:
            recovery_boot.run()

        setup.assert_called_once_with()
        self.assertEqual(values['prepared'], 0)

    def test_factory_reset_is_completed_before_first_boot_wizard(self):
        values, app, firmware = self.fake_modules(
            'raise AssertionError("application must not run")\n', app_status='idle'
        )
        app.discard_pending_update = lambda: True
        firmware.discard_pending_update = lambda: True
        Path('module_settings.json').write_text('{"devices":[]}')
        Path('module_settings.json.previous').write_text('{"devices":[]}')
        Path('.update-history.json').write_text('[]')
        Path('certs/trust').mkdir(parents=True)
        Path('certs/trust/root.der').write_bytes(b'old trust')
        credential_store.request_factory_reset('Setup-Maple-53!Harbour')

        with patch.dict(sys.modules, {
            'app_update': app,
            'firmware_update': firmware,
        }), patch.object(recovery_boot, '_run_initial_setup') as setup:
            recovery_boot.run()

        setup.assert_called_once_with()
        self.assertFalse(credential_store.is_provisioned())
        self.assertFalse(credential_store.factory_reset_pending())
        self.assertEqual(
            credential_store.bootstrap_key(), 'Setup-Maple-53!Harbour'
        )
        self.assertFalse(Path('module_settings.json').exists())
        self.assertFalse(Path('module_settings.json.previous').exists())
        self.assertFalse(Path('certs').exists())
        self.assertFalse(Path('.update-history.json').exists())
        self.assertEqual(values['prepared'], 0)

    def test_repeated_unhealthy_boots_request_recovery(self):
        self.assertEqual(recovery_boot._prepare_boot_attempt(), '')
        self.assertEqual(recovery_boot._prepare_boot_attempt(), '')
        self.assertEqual(recovery_boot._prepare_boot_attempt(), '')
        reason = recovery_boot._prepare_boot_attempt()

        self.assertIn('after 3 boots', reason)
        self.assertEqual(recovery_boot._read_recovery_state()['mode'], 'recovery')

    def test_trial_boots_keep_aggressive_rollback_threshold(self):
        self.assertEqual(recovery_boot._prepare_boot_attempt(trial=True), '')
        self.assertEqual(recovery_boot._prepare_boot_attempt(trial=True), '')
        reason = recovery_boot._prepare_boot_attempt(trial=True)
        self.assertIn('after 2 boots', reason)

    def test_trial_deadline_is_cancelled_after_both_layers_are_healthy(self):
        timer = SimpleNamespace(deinit=lambda: None)
        recovery_boot._trial_timer = timer
        app = SimpleNamespace(update_status=lambda: {'status': 'idle'})
        firmware = SimpleNamespace(update_status=lambda: {'status': 'idle'})
        with patch.dict(sys.modules, {'app_update': app, 'firmware_update': firmware}):
            self.assertTrue(recovery_boot.cancel_trial_deadline_if_healthy())
        self.assertIsNone(recovery_boot._trial_timer)

    def test_application_confirms_updates_only_after_portal_startup(self):
        source = (Path(self.previous_cwd) / 'iotmd_runtime.py').read_text()
        portal_start = source.index('portal_started = await start_admin_portal()')
        health_check = source.index('activation_health = startup.check(')
        confirmation = source.index('startup.confirm_updates(')
        self.assertLess(portal_start, health_check)
        self.assertLess(health_check, confirmation)
        service = (
            Path(self.previous_cwd) / 'services' / 'startup_service.py'
        ).read_text()
        self.assertIn('if firmware_update.confirm_update():', service)
        self.assertIn('if app_update.confirm_update():', service)

    def test_activation_exception_is_recorded_before_rollback(self):
        values, app, firmware = self.fake_modules('VALUE = 1\n', app_status='ready')
        app.update_status = lambda: {
            'status': values['app_status'], 'version': 'broken-application'
        }

        def fail_activation():
            raise ValueError('slot copy failed')

        app.activate_pending = fail_activation

        with patch.dict(sys.modules, {
            'app_update': app,
            'firmware_update': firmware,
        }):
            recovery_boot.run()

        import update_support
        failed = [
            item for item in update_support.update_history()
            if item.get('event') == 'activation_failed'
        ]
        self.assertEqual(failed[-1]['version'], 'broken-application')
        self.assertIn('slot copy failed', failed[-1]['detail'])
        self.assertEqual(values['app_rollbacks'], 1)


if __name__ == '__main__':
    unittest.main()
