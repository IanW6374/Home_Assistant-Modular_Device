import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import recovery_boot


class RecoveryBootTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)

    def tearDown(self):
        os.chdir(self.previous_cwd)
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
            'app_update.confirm_update()\n'
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
        reset.assert_not_called()

    def test_normal_return_without_confirmation_rolls_back_and_resets(self):
        values, app, firmware = self.fake_modules('VALUE = 1\n')

        with patch.dict(sys.modules, {
            'app_update': app,
            'firmware_update': firmware,
        }), patch.object(recovery_boot, '_reset') as reset:
            recovery_boot.run()

        self.assertEqual(values['app_rollbacks'], 1)
        reset.assert_called_once_with()

    def test_application_exception_rolls_back_trial_before_reraising(self):
        values, app, firmware = self.fake_modules(
            'raise RuntimeError("broken trial")\n'
        )

        with patch.dict(sys.modules, {
            'app_update': app,
            'firmware_update': firmware,
        }), patch.object(recovery_boot, '_reset') as reset:
            with self.assertRaisesRegex(RuntimeError, 'broken trial'):
                recovery_boot.run()

        self.assertEqual(values['app_rollbacks'], 1)
        reset.assert_called_once_with()

    def test_trial_deadline_is_cancelled_after_both_layers_are_healthy(self):
        timer = SimpleNamespace(deinit=lambda: None)
        recovery_boot._trial_timer = timer
        app = SimpleNamespace(update_status=lambda: {'status': 'idle'})
        firmware = SimpleNamespace(update_status=lambda: {'status': 'idle'})
        with patch.dict(sys.modules, {'app_update': app, 'firmware_update': firmware}):
            self.assertTrue(recovery_boot.cancel_trial_deadline_if_healthy())
        self.assertIsNone(recovery_boot._trial_timer)

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
