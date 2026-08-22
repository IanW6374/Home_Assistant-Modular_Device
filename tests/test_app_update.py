import hashlib
import json
import os
import tempfile
import unittest
import asyncio
import sys
from pathlib import Path

import app_update
import credential_store
import update_security
import update_support
from tools.build_update import build_bundle
from tools.build_update import certificate_entry
from tools.build_update import collect_files
from tools.build_update import generated_driver_index
from tools.build_update import is_ignored
from tools.build_update import load_ignore_patterns


class AppUpdateTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.previous_sys_path = list(sys.path)
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)
        self.private_key = bytes(range(1, 33))
        Path(update_security.VERIFICATION_KEY_PATH).write_bytes(
            update_security.public_key_bytes(self.private_key)
        )
        credential_store._reset_memory_backend()
        self.bundle_sequence = 0

    def tearDown(self):
        sys.path[:] = self.previous_sys_path
        credential_store._reset_memory_backend()
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def make_bundle(self, files, version='test-1', release_sequence=None):
        files = dict(files)
        if 'HA-Device.py' in files and 'app_settings.json' not in files:
            files['app_settings.json'] = b'{}'
        if release_sequence is None:
            self.bundle_sequence += 1
            release_sequence = self.bundle_sequence
        sources = []
        source_root = Path('source')
        for relative, content in files.items():
            source = source_root / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(content)
            sources.append((relative, source))
        build_bundle(
            Path(app_update.BUNDLE_PATH), version, sources,
            signing_key=self.private_key,
            release_sequence=release_sequence
        )

    def test_validates_application_bundle(self):
        self.make_bundle({'HA-Device.py': b'print("new")', 'device_modules/test.py': b'VALUE=1'})

        manifest = app_update.validate_bundle()

        self.assertEqual(manifest['version'], 'test-1')
        self.assertEqual(len(manifest['files']), 3)

    def test_rejects_tampered_bundle(self):
        self.make_bundle({'HA-Device.py': b'print("new")'})
        data = Path(app_update.BUNDLE_PATH).read_bytes()
        Path(app_update.BUNDLE_PATH).write_bytes(data[:-1] + bytes([data[-1] ^ 0xff]))

        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            app_update.validate_bundle()

    def test_application_manifest_has_no_device_profile(self):
        values = {
            'device_name': 'Controller', 'wifi_ssid': 'network',
            'wifi_password': 'wifi-password', 'mqtt_server': 'mqtt.local',
            'mqtt_port': '8883', 'mqtt_username': '', 'mqtt_password': '',
            'mqtt_ssl': True, 'portal_username': 'admin',
            'recovery_ap_password': 'Recovery-Access-Cedar-47!',
            'profile': 'whes', 'channel': 'stable', 'install_mode': 'upload',
        }
        config = credential_store.build_configuration(
            values, 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        credential_store.mark_provisioned(config)
        source = Path('different.py')
        source.write_bytes(b'new')
        build_bundle(
            Path(app_update.BUNDLE_PATH), 'other-profile',
            [('HA-Device.py', source), ('app_settings.json', source)],
            signing_key=self.private_key
        )

        manifest = app_update.validate_bundle()
        self.assertNotIn('application_profile', manifest)
        self.assertNotIn('bundle_scope', manifest)

    def test_protected_files_require_explicit_authorization(self):
        self.make_bundle({'certs/private.key': b'private-key'})

        with self.assertRaisesRegex(ValueError, 'protected file'):
            app_update.validate_bundle(allow_protected=False)
        self.assertEqual(
            app_update.validate_bundle(allow_protected=True)['files'][0]['path'],
            'certs/private.key'
        )

    def test_recovery_files_cannot_be_updated(self):
        for path in app_update.RECOVERY_FILES:
            self.make_bundle({path: b'broken'})
            with self.assertRaisesRegex(ValueError, 'recovery file'):
                app_update.validate_bundle()

    def test_activate_and_confirm_update(self):
        Path('HA-Device.py').write_bytes(b'old')
        self.make_bundle({'HA-Device.py': b'new', 'device_modules/new.py': b'VALUE=2'})
        app_update.stage_bundle()

        result = app_update.activate_pending()

        self.assertIn('activated update test-1', result)
        self.assertEqual(Path('HA-Device.py').read_bytes(), b'old')
        self.assertEqual(Path('.app-slots/a/HA-Device.py').read_bytes(), b'new')
        self.assertEqual(Path('.app-slots/a/device_modules/new.py').read_bytes(), b'VALUE=2')
        self.assertEqual(app_update.application_entry(), '.app-slots/a/HA-Device.py')
        self.assertEqual(app_update.update_status()['status'], 'trial')
        self.assertTrue(app_update.confirm_update())
        self.assertEqual(app_update.update_status()['status'], 'idle')
        self.assertEqual(app_update.active_slot(), 'a')
        self.assertEqual(app_update.running_version('old-version'), 'test-1')

    def test_protected_update_does_not_change_running_version(self):
        Path(app_update.VERSION_PATH).write_text('application-1')
        self.make_bundle({'certs/web.key': b'new-key'}, 'certificates-2')
        app_update.stage_bundle(allow_protected=True)
        app_update.activate_pending()

        self.assertTrue(app_update.confirm_update())
        self.assertEqual(app_update.running_version(), 'application-1')

    def test_optional_bundle_files_are_applied_selectively(self):
        Path('module_settings.json').write_bytes(b'old-module')
        self.make_bundle({
            'HA-Device.py': b'new-app',
            'module_settings.json': b'new-module',
            'certs/home-ca.der': b'new-cert'
        })
        state = app_update.stage_bundle(allow_protected=True)
        self.assertEqual(
            state['optional_groups'],
            ['module_settings', 'certificates']
        )
        app_update.configure_pending_update({
            'module_settings': False,
            'certificates': True
        })

        app_update.activate_pending()

        self.assertEqual(Path('.app-slots/a/HA-Device.py').read_bytes(), b'new-app')
        self.assertEqual(Path('module_settings.json').read_bytes(), b'old-module')
        self.assertEqual(Path('certs/home-ca.der').read_bytes(), b'new-cert')

    def test_cannot_select_optional_group_absent_from_staged_bundle(self):
        self.make_bundle({'HA-Device.py': b'new-app'})
        app_update.stage_bundle()

        with self.assertRaisesRegex(ValueError, 'not present'):
            app_update.configure_pending_update({'module_settings': True})

    def test_ready_update_can_be_discarded_from_recovery(self):
        self.make_bundle({'HA-Device.py': b'new-app'}, 'discard-me')
        app_update.stage_bundle()

        self.assertTrue(app_update.discard_pending_update())
        self.assertEqual(app_update.update_status()['status'], 'idle')
        self.assertFalse(Path(app_update.BUNDLE_PATH).exists())
        self.assertEqual(update_support.update_history()[-1]['event'], 'discarded')

    def test_unconfirmed_update_rolls_back_on_next_boot(self):
        Path('HA-Device.py').write_bytes(b'old')
        self.make_bundle({'HA-Device.py': b'new', 'new-file.py': b'new'})
        app_update.stage_bundle()
        app_update.activate_pending()

        self.assertTrue(Path('.app-slots/a/HA-Device.py').exists())

        result = app_update.activate_pending()

        self.assertIn('rolled back', result)
        self.assertEqual(Path('HA-Device.py').read_bytes(), b'old')
        self.assertFalse(Path('new-file.py').exists())
        self.assertFalse(Path('.app-slots/a').exists())
        self.assertEqual(app_update.update_status()['status'], 'idle')

    def test_confirmed_updates_alternate_application_slots(self):
        self.make_bundle({'HA-Device.py': b'app-a'}, 'version-a')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()

        self.make_bundle({'HA-Device.py': b'app-b'}, 'version-b')
        app_update.stage_bundle()
        app_update.activate_pending()

        self.assertEqual(app_update.application_entry(), '.app-slots/b/HA-Device.py')
        self.assertEqual(Path('.app-slots/a/HA-Device.py').read_bytes(), b'app-a')
        self.assertEqual(Path('.app-slots/b/HA-Device.py').read_bytes(), b'app-b')
        app_update.confirm_update()
        self.assertEqual(app_update.active_slot(), 'b')
        self.assertEqual(app_update.running_version(), 'version-b')

    def test_slot_integrity_detects_tampering_and_manual_rollback(self):
        self.make_bundle({'HA-Device.py': b'app-a'}, 'version-a')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()
        self.make_bundle({'HA-Device.py': b'app-b'}, 'version-b')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()

        self.assertEqual(app_update.previous_slot(), 'a')
        result = app_update.rollback_to_previous()
        self.assertEqual(result['active'], 'a')
        self.assertEqual(app_update.running_version(), 'version-a')

        Path('.app-slots/a/HA-Device.py').write_bytes(b'tampered')
        self.assertFalse(app_update.validate_slot_integrity('a'))
        self.assertEqual(app_update.active_slot(), '')

    def test_failed_second_slot_keeps_confirmed_slot_active(self):
        self.make_bundle({'HA-Device.py': b'stable'}, 'stable')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()

        self.make_bundle({'HA-Device.py': b'broken'}, 'broken')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.rollback_update()

        self.assertEqual(app_update.active_slot(), 'a')
        self.assertEqual(app_update.application_entry(), '.app-slots/a/HA-Device.py')
        self.assertEqual(Path('.app-slots/a/HA-Device.py').read_bytes(), b'stable')
        self.assertFalse(Path('.app-slots/b').exists())

    def test_bad_shared_certificate_rolls_back_with_failed_trial_slot(self):
        Path('certs').mkdir()
        Path('certs/web.key').write_bytes(b'working-key')
        self.make_bundle({'HA-Device.py': b'stable'}, 'stable')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()

        self.make_bundle({
            'HA-Device.py': b'trial',
            'certs/web.key': b'incorrect-key'
        }, 'trial')
        app_update.stage_bundle(allow_protected=True)
        app_update.configure_pending_update({'certificates': True})
        app_update.activate_pending()
        self.assertEqual(
            Path('certs/web.key').read_bytes(), b'incorrect-key'
        )

        app_update.activate_pending()

        self.assertEqual(
            Path('certs/web.key').read_bytes(), b'working-key'
        )
        self.assertEqual(app_update.active_slot(), 'a')
        self.assertFalse(Path('.app-slots/b').exists())

    def test_prepare_application_path_prefers_active_slot_and_library(self):
        self.make_bundle({'HA-Device.py': b'app', 'lib/example.py': b'VALUE=1'})
        app_update.stage_bundle()
        app_update.activate_pending()

        root = app_update.prepare_application_path()

        self.assertEqual(root, '.app-slots/a')
        self.assertEqual(sys.path[0], '.app-slots/a')
        self.assertEqual(sys.path[1], '.app-slots/a/lib')

    def test_interrupted_confirmation_is_completed_on_boot(self):
        self.make_bundle({'HA-Device.py': b'app'}, 'confirmed')
        app_update.stage_bundle()
        app_update.activate_pending()
        state = app_update.update_status()
        state['status'] = 'committing'
        app_update._write_json_atomic(app_update.STATE_PATH, state)

        result = app_update.activate_pending()

        self.assertIn('completed interrupted', result)
        self.assertEqual(app_update.active_slot(), 'a')
        self.assertEqual(app_update.update_status()['status'], 'idle')

    def test_rollback_repairs_slot_pointer_after_interrupted_commit(self):
        self.make_bundle({'HA-Device.py': b'stable'}, 'stable')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()
        self.make_bundle({'HA-Device.py': b'trial'}, 'trial')
        app_update.stage_bundle()
        app_update.activate_pending()
        state = app_update.update_status()
        state['status'] = 'committing'
        app_update._write_json_atomic(app_update.STATE_PATH, state)
        app_update._write_json_atomic(app_update.SLOT_STATE_PATH, {
            'active': 'b', 'versions': {'a': 'stable', 'b': 'trial'}
        })

        app_update.rollback_update()

        self.assertEqual(app_update.active_slot(), 'a')
        self.assertFalse(Path('.app-slots/b').exists())

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

    def test_receive_bundle_reports_verification_progress(self):
        self.make_bundle({'HA-Device.py': b'new application' * 200})
        payload = Path(app_update.BUNDLE_PATH).read_bytes()
        Path(app_update.BUNDLE_PATH).unlink()
        progress = []

        class Reader:
            def __init__(self, data):
                self.data = data

            async def read(self, size):
                chunk = self.data[:size]
                self.data = self.data[size:]
                return chunk

        asyncio.run(app_update.receive_bundle(
            Reader(payload), len(payload), progress_callback=lambda *value: progress.append(value)
        ))

        self.assertEqual(progress[0][0], 'receiving')
        self.assertEqual(progress[0][1], 0)
        self.assertIn('verification', [entry[0] for entry in progress])
        self.assertEqual(progress[-1][1], progress[-1][2])

    def test_receive_bundle_enforces_size_limit(self):
        class Reader:
            async def read(self, size):
                return b''

        with self.assertRaisesRegex(ValueError, 'size is not allowed'):
            asyncio.run(app_update.receive_bundle(Reader(), 100, max_bytes=50))

    def test_builder_excludes_local_configuration_by_default(self):
        root = Path('.')
        Path('HA-Device.py').write_text('app')
        Path('app_settings.json').write_text('{}')
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
            "MODULE_VERSION=1\nDEVICE_TYPE={'class':'sensor','subclass':{'EMS-Boiler':{}}}\n"
        )
        Path('component_versions.py').write_text('RUNTIME_VERSION=1\n')
        for name in (
            'settings_loader.py', 'hardware_platform.py', 'display.py',
            'web_portal_ui.py', 'web_portal.py',
            'release_update.py', 'certificate_manager.py',
            'api_security.py', 'configuration_manager.py', 'device_api.py',
            'fleet_management.py', 'portal_auth.py', 'portal_sessions.py',
            'resumable_upload.py', 'support_bundle.py',
            'message_broker.py', 'runtime_health.py', 'remote_logging.py',
            'timezone_rules.py', 'update_orchestrator.py',
            'device_modules/__init__.py', 'device_modules/loader.py',
            'device_modules/driver_index.py',
            'device_modules/contracts.py',
            'device_modules/base.py', 'device_modules/logging.py',
            'device_modules/validation.py', 'lib/mqtt_as.py',
            'lib/primitives/__init__.py', 'lib/primitives/encoder.py',
            'services/__init__.py', 'services/network_service.py',
            'services/messaging_service.py', 'services/portal_service.py',
            'services/update_service.py', 'services/event_service.py',
            'services/module_runtime.py'
        ):
            path = Path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('')

        default_names = [name for name, _ in collect_files(root)]
        settings_names = [
            name for name, _ in collect_files(root, include_settings=True)
        ]

        self.assertIn('HA-Device.py', default_names)
        self.assertIn('app_settings.json', default_names)
        self.assertIn('web_portal_ui.py', default_names)
        self.assertNotIn('portal_ui.py', default_names)
        self.assertTrue(set(default_names).isdisjoint(app_update.RECOVERY_FILES))
        self.assertNotIn('hardware_platform.py', default_names)
        self.assertNotIn('device_settings.json', default_names)
        self.assertNotIn('module_settings.json', default_names)
        self.assertIn('app_settings.json', settings_names)
        self.assertNotIn('device_settings.json', settings_names)
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

    def test_certificate_target_can_use_trust_store_subdirectory(self):
        source = Path('home-iot-root.der')
        source.write_bytes(b'root-ca')
        relative, resolved = certificate_entry(
            'trust/home-iot-root.der=' + str(source)
        )
        self.assertEqual(relative, 'certs/trust/home-iot-root.der')
        self.assertEqual(resolved, source.resolve())

        entries = collect_files(
            Path(self.previous_cwd), include_protected=True,
            certificates=['trust/home-iot-root.der=' + str(source)],
            protected_only=True
        )
        self.assertEqual(entries, [
            ('certs/trust/home-iot-root.der', source.resolve())
        ])

        with self.assertRaisesRegex(ValueError, 'safe path relative'):
            certificate_entry('../outside.der=' + str(source))

    def test_targeted_builder_selects_drivers_and_dependencies(self):
        root = Path(self.previous_cwd)
        module_path = Path('selected-modules.json')
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
                module_settings_path=module_path
            )
        }

        self.assertIn('device_modules/ems.py', names)
        self.assertIn('device_modules/max31865_pt1000.py', names)
        self.assertIn('device_modules/spi_bus.py', names)
        self.assertIn('device_modules/whes.py', names)
        self.assertIn('device_modules/modbus_transport.py', names)
        self.assertIn('device_modules/rs485_modbus.py', names)
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
                module_settings_path=module_path
            )
        }
        self.assertIn('app_settings.json', included_names)
        self.assertNotIn('device_settings.json', included_names)
        self.assertIn('module_settings.json', included_names)
        self.assertNotIn('selected-modules.json', included_names)

    def test_universal_builder_contains_every_driver_without_settings(self):
        root = Path(self.previous_cwd)
        names = {name for name, _ in collect_files(root, universal=True)}

        for driver in (
            'dht11.py', 'ems.py', 'grove_ac_voltage.py', 'hcsr04.py',
            'light.py', 'max31865_pt1000.py', 'modbus_transport.py',
            'rs485_modbus.py', 'switch_dimmer.py', 'switch_onoff.py', 'whes.py'
        ):
            self.assertIn('device_modules/' + driver, names)
        self.assertIn('device_modules/driver_index.py', names)
        self.assertIn('app_settings.json', names)
        self.assertNotIn('device_settings.json', names)
        self.assertNotIn('module_settings.json', names)
        generated = generated_driver_index(root).decode()
        self.assertIn("'sensor:WHES': 'whes'", generated)
        self.assertIn("'sensor:EMS-Boiler': 'ems'", generated)

    def test_universal_bundle_preserves_config_and_rejects_downgrade(self):
        values = {
            'device_name': 'Controller', 'wifi_ssid': 'network',
            'wifi_password': 'wifi-password', 'mqtt_server': 'mqtt.local',
            'mqtt_port': '8883', 'mqtt_username': '', 'mqtt_password': '',
            'mqtt_ssl': True, 'portal_username': 'admin',
            'recovery_ap_password': 'Recovery-Access-Cedar-47!',
            'profile': 'whes', 'channel': 'stable', 'install_mode': 'upload',
        }
        config = credential_store.build_configuration(
            values, 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        )
        credential_store.mark_provisioned(config)
        Path('module_settings.json').write_text('{"devices":[]}')
        source = Path('source.py')
        source.write_text('VALUE=1')
        build_bundle(
            Path(app_update.BUNDLE_PATH), 'universal-10',
            [('HA-Device.py', source), ('app_settings.json', source)],
            signing_key=self.private_key,
            release_sequence=10
        )
        manifest = app_update.validate_bundle()
        self.assertEqual(manifest['components']['runtime'], 1)
        self.assertNotIn('bundle_scope', manifest)
        app_update.stage_bundle(manifest=manifest)
        app_update.activate_pending()
        app_update.confirm_update()
        self.assertEqual(app_update.running_release_sequence(), 10)
        self.assertEqual(Path('module_settings.json').read_text(), '{"devices":[]}')

        build_bundle(
            Path(app_update.BUNDLE_PATH), 'universal-9',
            [('HA-Device.py', source), ('app_settings.json', source)],
            signing_key=self.private_key,
            release_sequence=9
        )
        with self.assertRaisesRegex(ValueError, 'not newer'):
            app_update.validate_bundle()

    def test_profile_bundle_cannot_bypass_release_sequence(self):
        Path(app_update.RELEASE_SEQUENCE_PATH).write_text('10')
        self.make_bundle(
            {'HA-Device.py': b'older profile runtime'},
            version='profile-10',
            release_sequence=10
        )

        with self.assertRaisesRegex(ValueError, 'not newer'):
            app_update.validate_bundle()

    def test_application_bundle_can_offer_optional_module_configuration(self):
        values = {
            'device_name': 'Controller', 'wifi_ssid': 'network',
            'wifi_password': 'wifi-password', 'mqtt_server': 'mqtt.local',
            'mqtt_port': '8883', 'mqtt_username': '', 'mqtt_password': '',
            'mqtt_ssl': True, 'portal_username': 'admin',
            'recovery_ap_password': 'Recovery-Access-Cedar-47!',
            'profile': 'whes', 'channel': 'stable', 'install_mode': 'upload',
        }
        credential_store.mark_provisioned(credential_store.build_configuration(
            values, 'Portal-Cedar-47!River', 'Console-Ash-82!Stone'
        ))
        source = Path('source.py')
        source.write_text('{}')
        build_bundle(
            Path(app_update.BUNDLE_PATH), 'bad-universal',
            [
                ('HA-Device.py', source),
                ('app_settings.json', source),
                ('module_settings.json', source)
            ],
            signing_key=self.private_key, release_sequence=11
        )
        manifest = app_update.validate_bundle()
        state = app_update.stage_bundle(manifest=manifest)
        self.assertIn('module_settings', state['optional_groups'])
        self.assertNotIn('module_settings.json', state['selected_paths'])

    def test_device_settings_cannot_be_packaged(self):
        path = Path('legacy-device-settings.json')
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'no longer supported'):
            collect_files(
                Path(self.previous_cwd),
                universal=True,
                device_settings_path=path
            )

    def test_firmware_manifest_freezes_the_complete_recovery_layer(self):
        manifest = (
            Path(self.previous_cwd) / 'firmware' / 'manifest.py'
        ).read_text()

        self.assertIn('include("$(PORT_DIR)/boards/manifest.py")', manifest)
        for path in (
            'main.py', 'core_metadata.py', 'recovery_boot.py', 'app_update.py', 'firmware_update.py',
            'hardware_platform.py', 'credential_store.py', 'setup_wizard.py',
            'factory_config.py', 'release_update.py', 'device_config.py'
        ):
            self.assertIn('module("' + path + '"', manifest)


if __name__ == '__main__':
    unittest.main()
