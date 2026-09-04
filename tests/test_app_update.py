import ast
import hashlib
import json
import os
import tempfile
import unittest
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app_update
import credential_store
import update_security
import update_support
from tools.build_update import build_bundle
from tools.build_update import certificate_entry
from tools.build_update import collect_files
from tools.build_update import compact_application_files
from tools.build_update import generated_driver_index
from tools.build_update import is_ignored
from tools.build_update import load_ignore_patterns
from tools.build_update import (
    chunk_runtime_string_literals, split_portal_route_modules,
)


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
        if 'iotmd.py' in files and 'app_settings.json' not in files:
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
        self.make_bundle({'iotmd.py': b'print("new")', 'device_modules/test.py': b'VALUE=1'})

        manifest = app_update.validate_bundle()

        self.assertEqual(manifest['version'], 'test-1')
        self.assertEqual(len(manifest['files']), 3)

    def test_rejects_tampered_bundle(self):
        self.make_bundle({'iotmd.py': b'print("new")'})
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
            [('iotmd.py', source), ('app_settings.json', source)],
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
        Path('iotmd.py').write_bytes(b'old')
        self.make_bundle({'iotmd.py': b'new', 'device_modules/new.py': b'VALUE=2'})
        app_update.stage_bundle()

        result = app_update.activate_pending()

        self.assertIn('activated update test-1', result)
        self.assertEqual(Path('iotmd.py').read_bytes(), b'old')
        self.assertEqual(Path('.app-slots/a/iotmd.py').read_bytes(), b'new')
        self.assertEqual(Path('.app-slots/a/device_modules/new.py').read_bytes(), b'VALUE=2')
        self.assertEqual(app_update.application_entry(), '.app-slots/a/iotmd.py')
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
            'iotmd.py': b'new-app',
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

        self.assertEqual(Path('.app-slots/a/iotmd.py').read_bytes(), b'new-app')
        self.assertEqual(Path('module_settings.json').read_bytes(), b'old-module')
        self.assertEqual(Path('certs/home-ca.der').read_bytes(), b'new-cert')

    def test_cannot_select_optional_group_absent_from_staged_bundle(self):
        self.make_bundle({'iotmd.py': b'new-app'})
        app_update.stage_bundle()

        with self.assertRaisesRegex(ValueError, 'not present'):
            app_update.configure_pending_update({'module_settings': True})

    def test_ready_update_can_be_discarded_from_recovery(self):
        self.make_bundle({'iotmd.py': b'new-app'}, 'discard-me')
        app_update.stage_bundle()

        self.assertTrue(app_update.discard_pending_update())
        self.assertEqual(app_update.update_status()['status'], 'idle')
        self.assertFalse(Path(app_update.BUNDLE_PATH).exists())
        self.assertEqual(update_support.update_history()[-1]['event'], 'discarded')

    def test_unconfirmed_update_rolls_back_on_next_boot(self):
        Path('iotmd.py').write_bytes(b'old')
        self.make_bundle({'iotmd.py': b'new', 'new-file.py': b'new'})
        app_update.stage_bundle()
        app_update.activate_pending()

        self.assertTrue(Path('.app-slots/a/iotmd.py').exists())

        result = app_update.activate_pending()

        self.assertIn('rolled back', result)
        self.assertEqual(Path('iotmd.py').read_bytes(), b'old')
        self.assertFalse(Path('new-file.py').exists())
        self.assertFalse(Path('.app-slots/a').exists())
        self.assertEqual(app_update.update_status()['status'], 'idle')

    def test_confirmed_updates_alternate_application_slots(self):
        self.make_bundle({'iotmd.py': b'app-a'}, 'version-a')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()

        self.make_bundle({'iotmd.py': b'app-b'}, 'version-b')
        app_update.stage_bundle()
        app_update.activate_pending()

        self.assertEqual(app_update.application_entry(), '.app-slots/b/iotmd.py')
        self.assertEqual(Path('.app-slots/a/iotmd.py').read_bytes(), b'app-a')
        self.assertEqual(Path('.app-slots/b/iotmd.py').read_bytes(), b'app-b')
        app_update.confirm_update()
        self.assertEqual(app_update.active_slot(), 'b')
        self.assertEqual(app_update.running_version(), 'version-b')

    def test_slot_integrity_detects_tampering_and_manual_rollback(self):
        self.make_bundle({'iotmd.py': b'app-a'}, 'version-a')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()
        self.make_bundle({'iotmd.py': b'app-b'}, 'version-b')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()

        self.assertEqual(app_update.previous_slot(), 'a')
        result = app_update.rollback_to_previous()
        self.assertEqual(result['active'], 'a')
        self.assertEqual(app_update.running_version(), 'version-a')

        Path('.app-slots/a/iotmd.py').write_bytes(b'tampered')
        self.assertFalse(app_update.validate_slot_integrity('a'))
        self.assertEqual(app_update.active_slot(), '')

    def test_failed_second_slot_keeps_confirmed_slot_active(self):
        self.make_bundle({'iotmd.py': b'stable'}, 'stable')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()

        self.make_bundle({'iotmd.py': b'broken'}, 'broken')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.rollback_update()

        self.assertEqual(app_update.active_slot(), 'a')
        self.assertEqual(app_update.application_entry(), '.app-slots/a/iotmd.py')
        self.assertEqual(Path('.app-slots/a/iotmd.py').read_bytes(), b'stable')
        self.assertFalse(Path('.app-slots/b').exists())

    def test_bad_shared_certificate_rolls_back_with_failed_trial_slot(self):
        Path('certs').mkdir()
        Path('certs/web.key').write_bytes(b'working-key')
        self.make_bundle({'iotmd.py': b'stable'}, 'stable')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()

        self.make_bundle({
            'iotmd.py': b'trial',
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
        self.make_bundle({'iotmd.py': b'app', 'lib/example.py': b'VALUE=1'})
        app_update.stage_bundle()
        app_update.activate_pending()

        root = app_update.prepare_application_path()

        self.assertEqual(root, '.app-slots/a')
        self.assertEqual(sys.path[0], '.app-slots/a')
        self.assertEqual(sys.path[1], '.app-slots/a/lib')

    def test_interrupted_confirmation_is_completed_on_boot(self):
        self.make_bundle({'iotmd.py': b'app'}, 'confirmed')
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
        self.make_bundle({'iotmd.py': b'stable'}, 'stable')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()
        self.make_bundle({'iotmd.py': b'trial'}, 'trial')
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
        self.make_bundle({'iotmd.py': b'new'})
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

    def test_receive_bundle_reserves_only_the_uploaded_bundle(self):
        self.make_bundle({'iotmd.py': b'new'})
        payload = Path(app_update.BUNDLE_PATH).read_bytes()
        Path(app_update.BUNDLE_PATH).unlink()

        class Reader:
            def __init__(self, data):
                self.data = data

            async def read(self, size):
                chunk = self.data[:size]
                self.data = self.data[size:]
                return chunk

        with patch.object(update_support, 'require_free_space') as require:
            asyncio.run(app_update.receive_bundle(Reader(payload), len(payload)))

        require.assert_called_once_with(len(payload))

    def test_activation_reclaims_inactive_slot_before_capacity_check(self):
        self.make_bundle({'iotmd.py': b'app-a'}, 'version-a')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()
        self.make_bundle({'iotmd.py': b'app-b'}, 'version-b')
        app_update.stage_bundle()
        app_update.activate_pending()
        app_update.confirm_update()
        self.assertEqual(app_update.active_slot(), 'b')
        self.assertTrue(Path('.app-slots/a/iotmd.py').exists())

        self.make_bundle({'iotmd.py': b'app-c'}, 'version-c')
        app_update.stage_bundle()

        def assert_inactive_reclaimed(_required):
            self.assertFalse(Path('.app-slots/a').exists())
            self.assertTrue(Path('.app-slots/b/iotmd.py').exists())

        with patch.object(
            update_support, 'require_free_space',
            side_effect=assert_inactive_reclaimed
        ):
            app_update.activate_pending()

        self.assertEqual(
            Path('.app-slots/a/iotmd.py').read_bytes(), b'app-c'
        )

    def test_universal_staging_reclaim_preserves_active_slot(self):
        Path('.app-slots/a').mkdir(parents=True)
        Path('.app-slots/b').mkdir(parents=True)
        Path('.app-slots/a/iotmd.py').write_bytes(b'active')
        Path('.app-slots/b/iotmd.py').write_bytes(b'old rollback')
        Path(app_update.SLOT_STATE_PATH).write_text(json.dumps({
            'active': 'a', 'versions': {'a': 'current'}, 'sequences': {'a': 1}
        }))

        self.assertTrue(app_update.reclaim_inactive_slot())
        self.assertEqual(
            Path('.app-slots/a/iotmd.py').read_bytes(), b'active'
        )
        self.assertFalse(Path('.app-slots/b').exists())

    def test_receive_bundle_reports_verification_progress(self):
        self.make_bundle({'iotmd.py': b'new application' * 200})
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
        Path('iotmd.py').write_text('app')
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
            'iotmd_runtime.py', 'settings_loader.py', 'hardware_platform.py', 'display.py',
            'application_upload.py',
            'portal_server.py', 'web_portal_ui.py', 'web_portal.py',
            'release_update.py', 'certificate_manager.py', 'certificate_lifecycle.py',
            'certificate_status.py',
            'certificate_enrollment_service.py', 'certificate_portal_actions.py',
            'certificate_portal_transport.py', 'certificate_portal_views.py',
            'certificate_trust.py',
            'portal_http.py', 'portal_live_views.py',
            'portal_presenters.py', 'portal_settings_views.py',
            'api_security.py', 'configuration_manager.py', 'api_contracts.py',
            'device_api.py', 'device_api_inventory.py', 'feature_flags.py',
            'network_transports.py', 'tls_sessions.py',
            'fleet_management.py', 'portal_auth.py', 'portal_contracts.py',
            'portal_routes.py', 'portal_view_models.py', 'portal_sessions.py',
            'resumable_upload.py', 'support_bundle.py',
            'message_broker.py', 'runtime_health.py', 'remote_logging.py',
            'timezone_rules.py', 'update_orchestrator.py',
            'universal_upload.py',
            'device_modules/__init__.py', 'device_modules/loader.py',
            'device_modules/driver_index.py',
            'device_modules/contracts.py', 'device_modules/resources.py',
            'device_modules/base.py', 'device_modules/logging.py',
            'device_modules/validation.py', 'lib/mqtt_as.py',
            'lib/primitives/__init__.py', 'lib/primitives/encoder.py',
            'services/__init__.py', 'services/network_service.py',
            'services/messaging_service.py', 'services/portal_service.py',
            'services/home_assistant_service.py',
            'services/update_service.py', 'services/event_service.py',
            'services/event_sinks.py', 'services/module_runtime.py',
            'services/startup_service.py',
            'application/__init__.py',
            'application/context.py', 'application/lifecycle.py',
            'application/boot_health.py'
        ):
            path = Path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('')

        default_names = [name for name, _ in collect_files(root)]
        settings_names = [
            name for name, _ in collect_files(root, include_settings=True)
        ]

        self.assertIn('iotmd.py', default_names)
        self.assertIn('iotmd_runtime.py', default_names)
        self.assertIn('app_settings.json', default_names)
        self.assertIn('portal_server.py', default_names)
        self.assertIn('web_portal_ui.py', default_names)
        for certificate_module in (
            'certificate_enrollment_service.py', 'certificate_portal_actions.py',
            'certificate_portal_transport.py', 'certificate_portal_views.py',
            'certificate_trust.py',
        ):
            self.assertIn(certificate_module, default_names)
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

    def test_compact_builder_keeps_entry_and_provenance_as_source(self):
        entry = Path('iotmd.py')
        runtime = Path('iotmd_runtime.py')
        portal_server = Path('portal_server.py')
        web_portal = Path('web_portal.py')
        provenance = Path('component_versions.py')
        module = Path('module.py')
        settings = Path('app_settings.json')
        entry.write_text('import module\n')
        runtime.write_text('VALUE = 3\n')
        portal_server.write_text('from web_portal import start_web_portal\n')
        web_portal.write_text('PORTAL_IMPLEMENTATION = 1\n')
        provenance.write_text('RUNTIME_VERSION = 1\n')
        module.write_text('VALUE = 1\n')
        settings.write_text('{}')
        compiler = Path('mpy-cross')
        compiler.write_bytes(b'compiler')

        def compile_module(command, **_kwargs):
            output = Path(command[command.index('-o') + 1])
            output.write_bytes(b'MPY' + Path(command[-1]).read_bytes())
            return SimpleNamespace(returncode=0, stdout='', stderr='')

        files = [
            ('iotmd.py', entry), ('component_versions.py', provenance),
            ('iotmd_runtime.py', runtime),
            ('portal_server.py', portal_server),
            ('module.py', module), ('app_settings.json', settings),
        ]
        with patch('tools.build_update.subprocess.run', side_effect=compile_module):
            compact, overrides = compact_application_files(
                files, {'module.py': b'VALUE = 2\n'}, compiler
            )

        names = [name for name, _path in compact]
        self.assertEqual(
            names,
            [
                'iotmd.py', 'component_versions.py', 'iotmd_runtime.mpy',
                'portal_server.mpy', 'module.mpy', 'app_settings.json'
            ]
        )
        self.assertEqual(overrides['iotmd_runtime.mpy'], b'MPYVALUE = 3\n')
        self.assertEqual(
            overrides['portal_server.mpy'],
            b'MPYPORTAL_IMPLEMENTATION = 1\n'
        )
        self.assertEqual(overrides['module.mpy'], b'MPYVALUE = 2\n')
        self.assertNotIn('module.py', overrides)

    def test_portal_route_split_removes_large_nested_dispatchers(self):
        source = (
            'from portal_presenters import *\n\n'
            'async def start_web_portal():\n'
            '    async def handle_client():\n'
            '        async def handle_access_routes():\n'
            '            nonlocal login_failures\n'
            '            login_failures += 1\n'
            '            return True\n\n'
            '        async def handle_settings_routes():\n'
            '            return settings_getter()\n\n'
            '        async def handle_upload_routes():\n'
            '            return upload_progress_by_id\n\n'
            '        async def handle_live_routes():\n'
            '            return status_snapshot.get()\n'
            '        try:\n'
            '            return await handle_live_routes()\n'
            '        except Exception:\n'
            '            return False\n'
        ).encode()

        compact_source, routes = split_portal_route_modules(source)
        compact_text = compact_source.decode()

        self.assertIn('import portal_route_settings', compact_text)
        self.assertIn('import portal_route_live', compact_text)
        self.assertIn('import portal_route_access', compact_text)
        self.assertIn('import portal_route_upload', compact_text)
        self.assertIn(
            'return await portal_route_settings.handle_settings_routes(',
            compact_text
        )
        self.assertNotIn('return settings_getter()', compact_text)
        self.assertNotIn('return status_snapshot.get()', compact_text)
        self.assertIn(
            'return (True, login_failures, password_verifier,',
            routes['portal_route_access.py'].decode()
        )
        self.assertIn(
            'async def handle_settings_routes(',
            routes['portal_route_settings.py'].decode()
        )
        self.assertIn(
            'async def handle_live_routes(',
            routes['portal_route_live.py'].decode()
        )
        self.assertIn(
            'async def handle_upload_routes(',
            routes['portal_route_upload.py'].decode()
        )

    def test_large_renderer_strings_are_chunked_until_function_execution(self):
        long_value = ('portal-status-' * 500) + '…'
        source = (
            'MODULE_VALUE = ' + repr(long_value) + '\n'
            'def render():\n'
            '    return ' + repr(long_value) + '\n'
        )

        transformed = chunk_runtime_string_literals(source, 256)
        tree = ast.parse(transformed)
        module_assignment = tree.body[0].value
        renderer_return = tree.body[1].body[0].value

        self.assertIsInstance(module_assignment, ast.Constant)
        self.assertIsInstance(renderer_return, ast.Call)
        renderer_chunks = renderer_return.args[0].elts
        self.assertTrue(renderer_chunks)
        self.assertLessEqual(
            max(len(item.value.encode('utf-8')) for item in renderer_chunks),
            256,
        )
        namespace = {}
        exec(compile(tree, '<chunked>', 'exec'), namespace)
        self.assertEqual(namespace['MODULE_VALUE'], long_value)
        self.assertEqual(namespace['render'](), long_value)

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
        self.assertIn('v3/runtime/iotmd_next/platform.py', names)
        self.assertIn('v3/runtime/iotmd_next/storage.py', names)
        self.assertIn('v3/runtime/iotmd_next/paired_update.py', names)
        self.assertIn('v3/runtime/iotmd_next/configuration.py', names)
        self.assertIn('v3/runtime/iotmd_next/kernel.py', names)
        self.assertIn('v3/runtime/iotmd_next/reference_sensor.py', names)
        self.assertIn('v3/runtime/iotmd_next/resources.py', names)
        self.assertIn('v3/runtime/iotmd_next/supervisor.py', names)
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
            [('iotmd.py', source), ('app_settings.json', source)],
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
            [('iotmd.py', source), ('app_settings.json', source)],
            signing_key=self.private_key,
            release_sequence=9
        )
        with self.assertRaisesRegex(ValueError, 'not newer'):
            app_update.validate_bundle()

    def test_profile_bundle_cannot_bypass_release_sequence(self):
        Path(app_update.RELEASE_SEQUENCE_PATH).write_text('10')
        self.make_bundle(
            {'iotmd.py': b'older profile runtime'},
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
                ('iotmd.py', source),
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
            'hardware_platform.py', 'boot_state.py', 'credential_store.py', 'setup_wizard.py',
            'factory_config.py', 'release_update.py', 'tls_sessions.py', 'device_config.py'
        ):
            self.assertIn('module("' + path + '"', manifest)


if __name__ == '__main__':
    unittest.main()
