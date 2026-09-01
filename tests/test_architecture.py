import asyncio
import ast
import hashlib
import tempfile
import unittest
from pathlib import Path

from application import ApplicationContext, RuntimeState, TaskSupervisor
from application import evaluate_boot_health
from application.lifecycle import ApplicationLifecycle, LifecycleError
from device_modules.resources import ResourceConflict, ResourceManager, validate_resources
from portal_contracts import PortalDependencies
from portal_routes import ROUTES
from portal_view_models import overview_metrics, update_check_summary
from resumable_upload import ResumableUploadStore
from services.update_service import UpdateService
from tools.check_architecture import (
    architecture_errors, frozen_dependency_errors, module_imported_roots,
)


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_repository_architecture_gates_pass(self):
        self.assertEqual(architecture_errors(), [])

    def test_frozen_recovery_contains_project_import_closure(self):
        self.assertEqual(frozen_dependency_errors(), [])

    def test_compact_entry_rejects_an_old_core_before_runtime_import(self):
        tree = ast.parse(Path('iotmd.py').read_text(), filename='iotmd.py')
        runtime_import = next(
            node.lineno for node in tree.body
            if isinstance(node, ast.Import) and
            any(alias.name == 'iotmd_runtime' for alias in node.names)
        )
        guard = next(
            node.lineno for node in tree.body
            if isinstance(node, ast.If) and
            'core_api' in ast.unparse(node.test)
        )
        self.assertLess(guard, runtime_import)

    def test_activation_heap_policy_is_loaded_through_settings_boundary(self):
        source = Path('iotmd_runtime.py').read_text()
        self.assertIn(
            'minimum_activation_heap_bytes = '
            'device_settings.minimum_activation_heap_bytes',
            source
        )
        self.assertNotIn(
            "getattr(device_config, 'MINIMUM_ACTIVATION_HEAP_BYTES'", source
        )

    def test_certificate_administration_is_lazy_during_normal_boot(self):
        expectations = {
            'certificate_portal_actions.py': {
                'certificate_enrollment_service', 'certificate_trust',
            },
            'certificate_portal_transport.py': {'certificate_portal_views'},
            'portal_settings_views.py': {'certificate_portal_views'},
            'web_portal.py': {'certificate_portal_transport'},
        }
        for relative, forbidden in expectations.items():
            with self.subTest(relative=relative):
                self.assertFalse(module_imported_roots(relative) & forbidden)

    def test_every_authenticated_portal_route_has_explicit_policy(self):
        for route in (
            '/settings', '/wifi-settings', '/messaging', '/device-api',
            '/certificates', '/configuration-backup', '/updates', '/logs',
            '/api/restart-required', '/restart-device', '/shutdown-device',
        ):
            self.assertIn(route, ROUTES)

    def test_portal_view_models_do_not_emit_html(self):
        metrics = overview_metrics({'device_name': 'kitchen'})
        self.assertEqual(metrics[0]['value'], 'kitchen')
        self.assertEqual(
            next(item['label'] for item in metrics if item['key'] == 'syslog'),
            'Remote syslog'
        )
        summary = update_check_summary({
            'release_automatic_check_status': 'Up to date',
            'release_automatic_last_checked': '08:15',
        })
        self.assertEqual(summary['tone'], 'good')
        self.assertNotIn('<', summary['text'])

    def test_application_lifecycle_rejects_skipped_startup_phases(self):
        state = RuntimeState()
        lifecycle = ApplicationLifecycle(state)
        lifecycle.transition('starting')
        lifecycle.transition('network-ready')
        self.assertEqual(lifecycle.snapshot()['state'], 'network-ready')
        self.assertEqual(lifecycle.snapshot()['device_state'], 'initialising')
        with self.assertRaises(LifecycleError):
            lifecycle.transition('services-ready')

    def test_activation_health_separates_local_gates_from_external_degradation(self):
        result = evaluate_boot_health(
            {'platform': 'esp32-s3', 'features': {'psram': True}},
            2 * 1024 * 1024, 512 * 1024,
            ('network', 'portal'), {
                'network': 'online', 'portal': 'listening',
                'mqtt': 'degraded', 'syslog': 'degraded',
            }, watchdog_required=True, watchdog_ready=True,
        )
        self.assertTrue(result['healthy'])
        self.assertEqual(len(result['degraded']), 2)

    def test_activation_health_blocks_low_heap_or_failed_local_portal(self):
        result = evaluate_boot_health(
            {'platform': 'esp32-s3', 'features': {'psram': True}},
            200000, 512 * 1024, ('network', 'portal'), {
                'network': 'online', 'portal': 'failed',
            }, watchdog_required=True, watchdog_ready=False,
        )
        self.assertFalse(result['healthy'])
        self.assertEqual(len(result['failures']), 3)

    def test_application_context_is_explicit_and_sealed(self):
        state = RuntimeState({'phase': 'starting'})
        context = ApplicationContext({'device_id': 'device-1'}, state=state)
        service = object()
        context.register('modules', service)
        context.seal(('modules',))
        self.assertIs(context.service('modules'), service)
        self.assertEqual(context.inventory()['state']['phase'], 'starting')
        with self.assertRaisesRegex(RuntimeError, 'sealed'):
            context.register('portal', object())

    def test_task_supervisor_reports_critical_failure(self):
        class Events:
            def __init__(self):
                self.values = []

            def emit(self, *args, **kwargs):
                self.values.append((args, kwargs))

        async def exercise():
            events = Events()
            failures = []
            supervisor = TaskSupervisor(
                events, lambda name, error: failures.append((name, str(error)))
            )

            async def fail():
                raise RuntimeError('broken transport')

            supervisor.start('api', fail(), critical=True)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertEqual(supervisor.status('api')['status'], 'failed')
            self.assertEqual(supervisor.status('api')['state'], 'failed')
            self.assertEqual(supervisor.status('api')['failure_count'], 1)
            self.assertEqual(supervisor.status('api')['start_count'], 1)
            self.assertEqual(
                supervisor.status('api')['last_error'], 'broken transport'
            )
            self.assertTrue(supervisor.status('api')['critical'])
            self.assertEqual(failures, [('api', 'broken transport')])
            self.assertTrue(any(value[0][0] == 'task_failed' for value in events.values))

        asyncio.run(exercise())

    def test_task_supervisor_exposes_heartbeat_and_degraded_health(self):
        async def exercise():
            ticks = iter((100, 125, 150, 175))
            release = asyncio.Event()
            supervisor = TaskSupervisor(clock=lambda: next(ticks))

            async def worker():
                await release.wait()

            supervisor.start('worker', worker())
            await asyncio.sleep(0)
            self.assertTrue(supervisor.heartbeat('worker'))
            health = supervisor.status('worker')
            self.assertEqual(health['state'], 'running')
            self.assertEqual(health['started_ms'], 100)
            self.assertEqual(health['last_success_ms'], 125)

            self.assertTrue(supervisor.degrade('worker', 'temporary timeout'))
            health = supervisor.status('worker')
            self.assertEqual(health['state'], 'degraded')
            self.assertEqual(health['failure_count'], 1)
            self.assertEqual(health['last_error'], 'temporary timeout')

            release.set()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            health = supervisor.status('worker')
            self.assertEqual(health['state'], 'complete')
            self.assertEqual(health['last_success_ms'], 150)

        asyncio.run(exercise())

    def test_resource_manager_rejects_conflicts_and_accepts_matching_shared_bus(self):
        manager = ResourceManager()
        manager.reserve('spi', 1, 'sensor-a', shared=True, signature=(12, 11, 13))
        manager.reserve('spi', 1, 'sensor-b', shared=True, signature=(12, 11, 13))
        with self.assertRaises(ResourceConflict):
            manager.reserve('spi', 1, 'sensor-c', shared=True, signature=(4, 5, 6))
        manager.reserve('gpio', 10, 'sensor-a')
        with self.assertRaises(ResourceConflict):
            manager.reserve('gpio', 10, 'sensor-b')

    def test_resource_manager_supports_logical_injected_resources(self):
        created = []
        manager = ResourceManager({'uart': lambda resource: created.append(resource) or object()})
        manager.reserve(
            'uart', 1, 'sensor-a', logical_name='sensor-a.rs485.uart'
        )
        scope = manager.scope('sensor-a')
        first = scope.acquire('sensor-a.rs485.uart')
        second = scope.acquire('sensor-a.rs485.uart')
        self.assertIs(first, second)
        self.assertEqual(len(created), 1)
        self.assertEqual(
            scope.bindings()['sensor-a.rs485.uart'], 'uart:1'
        )
        with self.assertRaises(PermissionError):
            manager.acquire('sensor-a.rs485.uart', 'sensor-b')

    def test_configured_uart_conflict_is_detected_before_driver_setup(self):
        errors, _manager = validate_resources([
            {'uuid': '0001', 'rs485': {'uart': 1, 'tx': 17, 'rx': 18}},
            {'uuid': '0002', 'ems': {'uart': 1, 'tx': 5, 'rx': 6}},
        ])
        self.assertTrue(any('uart:1' in error for error in errors))

    def test_portal_dependencies_are_named_and_report_capabilities(self):
        dependencies = PortalDependencies(
            {'https': True}, {'status.get': lambda: {}, 'unused': None}
        )
        self.assertEqual(dependencies.capabilities(), ['status.get'])
        with self.assertRaisesRegex(RuntimeError, 'required portal handler'):
            dependencies.require('modules.list')

    def test_update_service_owns_append_completion_and_cleanup(self):
        async def exercise():
            with tempfile.TemporaryDirectory() as directory:
                payload = b'signed-update-artifact'
                digest = hashlib.sha256(payload).hexdigest()
                store = ResumableUploadStore(directory, maximum_bytes=1024)
                installed = []

                async def receiver(reader, length, params):
                    installed.append(await reader.read(length))
                    self.assertIn('_progress', params)
                    return 'verified and staged'

                class Reader:
                    async def read(self, _length):
                        return payload

                service = UpdateService(store, {'application': receiver})
                service.begin({
                    'id': 'architecture-test', 'kind': 'application',
                    'total_bytes': len(payload), 'sha256': digest,
                })
                await service.append('architecture-test', 0, Reader(), len(payload))
                result = await service.complete('architecture-test')
                self.assertEqual(result, 'verified and staged')
                self.assertEqual(installed, [payload])
                with self.assertRaisesRegex(ValueError, 'does not exist'):
                    service.status('architecture-test')

        asyncio.run(exercise())


if __name__ == '__main__':
    unittest.main()
