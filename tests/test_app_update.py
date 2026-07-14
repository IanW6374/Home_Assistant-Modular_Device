import hashlib
import json
import os
import tempfile
import unittest
import asyncio
from pathlib import Path

import app_update
from tools.build_update import build_bundle
from tools.build_update import collect_files
from tools.build_update import is_ignored
from tools.build_update import load_ignore_patterns
from tools.build_update import normalized_device_settings


class AppUpdateTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def make_bundle(self, files, version='test-1'):
        sources = []
        source_root = Path('source')
        for relative, content in files.items():
            source = source_root / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(content)
            sources.append((relative, source))
        build_bundle(Path(app_update.BUNDLE_PATH), version, sources)

    def test_validates_application_bundle(self):
        self.make_bundle({'HA-Device.py': b'print("new")', 'device_modules/test.py': b'VALUE=1'})

        manifest = app_update.validate_bundle()

        self.assertEqual(manifest['version'], 'test-1')
        self.assertEqual(len(manifest['files']), 2)

    def test_rejects_tampered_bundle(self):
        self.make_bundle({'HA-Device.py': b'print("new")'})
        data = Path(app_update.BUNDLE_PATH).read_bytes()
        Path(app_update.BUNDLE_PATH).write_bytes(data[:-1] + bytes([data[-1] ^ 0xff]))

        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            app_update.validate_bundle()

    def test_protected_files_require_explicit_authorization(self):
        self.make_bundle({'secrets.py': b'wifi_password="secret"'})

        with self.assertRaisesRegex(ValueError, 'protected file'):
            app_update.validate_bundle(allow_protected=False)
        self.assertEqual(
            app_update.validate_bundle(allow_protected=True)['files'][0]['path'],
            'secrets.py'
        )

    def test_recovery_files_cannot_be_updated(self):
        self.make_bundle({'main.py': b'broken'})

        with self.assertRaisesRegex(ValueError, 'recovery file'):
            app_update.validate_bundle()

    def test_activate_and_confirm_update(self):
        Path('HA-Device.py').write_bytes(b'old')
        self.make_bundle({'HA-Device.py': b'new', 'device_modules/new.py': b'VALUE=2'})
        app_update.stage_bundle()

        result = app_update.activate_pending()

        self.assertIn('activated update test-1', result)
        self.assertEqual(Path('HA-Device.py').read_bytes(), b'new')
        self.assertEqual(Path('device_modules/new.py').read_bytes(), b'VALUE=2')
        self.assertEqual(app_update.update_status()['status'], 'trial')
        self.assertTrue(app_update.confirm_update())
        self.assertEqual(app_update.update_status()['status'], 'idle')
        self.assertEqual(app_update.running_version('old-version'), 'test-1')

    def test_protected_update_does_not_change_running_version(self):
        Path(app_update.VERSION_PATH).write_text('application-1')
        self.make_bundle({'secrets.py': b'wifi_password="new"'}, 'credentials-2')
        app_update.stage_bundle(allow_protected=True)
        app_update.activate_pending()

        self.assertTrue(app_update.confirm_update())
        self.assertEqual(app_update.running_version(), 'application-1')

    def test_optional_bundle_files_are_applied_selectively(self):
        Path('device_settings.json').write_bytes(b'old-device')
        Path('module_settings.json').write_bytes(b'old-module')
        Path('secrets.py').write_bytes(b'old-secrets')
        self.make_bundle({
            'HA-Device.py': b'new-app',
            'device_settings.json': b'new-device',
            'module_settings.json': b'new-module',
            'secrets.py': b'new-secrets',
            'certs/home-ca.der': b'new-cert'
        })
        state = app_update.stage_bundle(allow_protected=True)
        self.assertEqual(
            state['optional_groups'],
            ['device_settings', 'module_settings', 'secrets', 'certificates']
        )
        self.assertNotIn('device_settings.json', state['selected_paths'])
        app_update.configure_pending_update({
            'device_settings': True,
            'module_settings': False,
            'secrets': False,
            'certificates': True
        })

        app_update.activate_pending()

        self.assertEqual(Path('HA-Device.py').read_bytes(), b'new-app')
        self.assertEqual(Path('device_settings.json').read_bytes(), b'new-device')
        self.assertEqual(Path('module_settings.json').read_bytes(), b'old-module')
        self.assertEqual(Path('secrets.py').read_bytes(), b'old-secrets')
        self.assertEqual(Path('certs/home-ca.der').read_bytes(), b'new-cert')

    def test_cannot_select_optional_group_absent_from_staged_bundle(self):
        self.make_bundle({'HA-Device.py': b'new-app'})
        app_update.stage_bundle()

        with self.assertRaisesRegex(ValueError, 'not present'):
            app_update.configure_pending_update({'device_settings': True})

    def test_unconfirmed_update_rolls_back_on_next_boot(self):
        Path('HA-Device.py').write_bytes(b'old')
        self.make_bundle({'HA-Device.py': b'new', 'new-file.py': b'new'})
        app_update.stage_bundle()
        app_update.activate_pending()

        result = app_update.activate_pending()

        self.assertIn('rolled back', result)
        self.assertEqual(Path('HA-Device.py').read_bytes(), b'old')
        self.assertFalse(Path('new-file.py').exists())
        self.assertEqual(app_update.update_status()['status'], 'idle')

    def test_receive_bundle_streams_and_stages_upload(self):
        self.make_bundle({'HA-Device.py': b'new'})
        payload = Path(app_update.BUNDLE_PATH).read_bytes()
        Path(app_update.BUNDLE_PATH).unlink()

        class Reader:
            def __init__(self, data):
                self.data = data

            async def read(self, size):
                chunk = self.data[:size]
                self.data = self.data[size:]
                return chunk

        state = asyncio.run(app_update.receive_bundle(Reader(payload), len(payload)))

        self.assertEqual(state['status'], 'ready')
        self.assertEqual(state['version'], 'test-1')
        self.assertEqual(Path(app_update.BUNDLE_PATH).read_bytes(), payload)

    def test_receive_bundle_enforces_size_limit(self):
        class Reader:
            async def read(self, size):
                return b''

        with self.assertRaisesRegex(ValueError, 'size is not allowed'):
            asyncio.run(app_update.receive_bundle(Reader(), 100, max_bytes=50))

    def test_builder_excludes_local_configuration_by_default(self):
        root = Path('.')
        Path('HA-Device.py').write_text('app')
        Path('device_settings.json').write_text(json.dumps({
            'device': {'module_settings_file': 'module_settings.json'}
        }))
        Path('module_settings.json').write_text(json.dumps({
            'devices': [{
                'name': 'EMS',
                'uuid': '0001',
                'type': {'class': 'sensor', 'subclass': 'EMS-Boiler'},
                'entities': {'0': {'class': 'temperature'}}
            }]
        }))
        Path('device_modules').mkdir()
        Path('device_modules/ems.py').write_text(
            "DEVICE_TYPE={'class':'sensor','subclass':{'EMS-Boiler':{}}}\n"
        )
        for name in (
            'settings_loader.py', 'hardware_platform.py', 'local_display.py', 'web_portal.py',
            'device_modules/__init__.py', 'device_modules/loader.py',
            'device_modules/base.py', 'device_modules/logging.py',
            'device_modules/validation.py', 'lib/mqtt_as.py',
            'lib/primitives/__init__.py', 'lib/primitives/encoder.py'
        ):
            path = Path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('')

        default_names = [name for name, _ in collect_files(root)]
        settings_names = [
            name for name, _ in collect_files(root, include_settings=True)
        ]

        self.assertIn('HA-Device.py', default_names)
        self.assertNotIn('device_settings.json', default_names)
        self.assertNotIn('module_settings.json', default_names)
        self.assertIn('device_settings.json', settings_names)
        self.assertIn('module_settings.json', settings_names)

    def test_builder_honours_ignore_file_and_examples_pattern(self):
        Path('.build_update_ignore').write_text(
            'examples/\n__pycache__/\n*.bak\n'
        )
        patterns = load_ignore_patterns(Path('.'))

        self.assertTrue(is_ignored('examples/demo.json', patterns))
        self.assertTrue(is_ignored('lib/__pycache__/module.pyc', patterns))
        self.assertTrue(is_ignored('device_modules/old.py.bak', patterns))
        self.assertFalse(is_ignored('device_modules/ems.py', patterns))

    def test_targeted_builder_selects_drivers_and_dependencies(self):
        root = Path(self.previous_cwd)
        device_path = Path('selected-device.json')
        module_path = Path('selected-modules.json')
        device_path.write_text(json.dumps({
            'device': {'module_settings_file': 'selected-modules.json'}
        }))
        module_path.write_text(json.dumps({
            'devices': [
                {'type': {'class': 'sensor', 'subclass': 'EMS-Boiler'}},
                {'type': {'class': 'sensor', 'subclass': 'MAX31865-PT1000'}},
                {'type': {'class': 'sensor', 'subclass': 'WHES'}},
                {'type': {'class': 'sensor', 'subclass': 'hcsr04'}},
                {'type': {'class': 'switch', 'subclass': 'onoff'}}
            ]
        }))

        names = {
            name for name, _ in collect_files(
                root,
                device_settings_path=device_path,
                module_settings_path=module_path
            )
        }

        self.assertIn('device_modules/ems.py', names)
        self.assertIn('device_modules/max31865_pt1000.py', names)
        self.assertIn('device_modules/spi_bus.py', names)
        self.assertIn('device_modules/whes.py', names)
        self.assertIn('device_modules/pico_2ch_rs485.py', names)
        self.assertIn('device_modules/hcsr04.py', names)
        self.assertIn('lib/uhcsr04/hcsr04.py', names)
        self.assertIn('device_modules/switch_onoff.py', names)
        self.assertIn('lib/primitives/pushbutton.py', names)
        self.assertIn('lib/primitives/delay_ms.py', names)
        self.assertNotIn('device_modules/grove_ac_voltage.py', names)
        self.assertNotIn('device_modules/light.py', names)

        included_names = {
            name for name, _ in collect_files(
                root,
                device_settings_path=device_path,
                module_settings_path=module_path
            )
        }
        self.assertIn('device_settings.json', included_names)
        self.assertIn('module_settings.json', included_names)
        self.assertNotIn('selected-device.json', included_names)
        self.assertNotIn('selected-modules.json', included_names)

    def test_packaged_device_settings_reference_normalized_module_name(self):
        normalized = normalized_device_settings({
            'device': {'module_settings_file': 'custom/ems-settings.json'},
            'web_portal': {'enabled': True}
        })

        self.assertEqual(
            normalized['device']['module_settings_file'],
            'module_settings.json'
        )
        self.assertTrue(normalized['web_portal']['enabled'])


if __name__ == '__main__':
    unittest.main()
