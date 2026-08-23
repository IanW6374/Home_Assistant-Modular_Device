import asyncio
import hashlib
import tempfile
import unittest

from application import ApplicationContext, RuntimeState, TaskSupervisor
from application.lifecycle import ApplicationLifecycle, LifecycleError
from device_modules.resources import ResourceConflict, ResourceManager, validate_resources
from portal_contracts import PortalDependencies
from portal_routes import ROUTES
from portal_view_models import overview_metrics, update_check_summary
from resumable_upload import ResumableUploadStore
from services.update_service import UpdateService


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_every_authenticated_portal_route_has_explicit_policy(self):
        for route in (
            '/settings', '/wifi-settings', '/mqtt', '/device-api',
            '/certificates', '/configuration-backup', '/updates', '/logs',
        ):
            self.assertIn(route, ROUTES)

    def test_portal_view_models_do_not_emit_html(self):
        metrics = overview_metrics({'device_name': 'kitchen'})
        self.assertEqual(metrics[0]['value'], 'kitchen')
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
        with self.assertRaises(LifecycleError):
            lifecycle.transition('services-ready')

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
            self.assertEqual(failures, [('api', 'broken transport')])
            self.assertTrue(any(value[0][0] == 'task_failed' for value in events.values))

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
