"""Lazy bridge from the compatibility runtime to v3 qualification evidence."""


class AlphaQualificationService:
    """Keep v3 imports and native namespace allocation off the critical boot path."""

    def __init__(self, device_id, release_getter, clock, recorder_factory=None):
        self.device_id = str(device_id)
        self.release_getter = release_getter
        self.clock = clock
        self.recorder_factory = recorder_factory
        self.recorder = None
        self.platform = None
        self.error = ''

    def start(self):
        if self.recorder is not None:
            return True
        try:
            if self.recorder_factory is None:
                from v3.runtime.iotmd_next.platform import Platform
                from v3.runtime.iotmd_next.storage import TransactionalNamespace
                from v3.runtime.iotmd_next.qualification import OperationalQualification
                self.platform = Platform()
                namespace = TransactionalNamespace(self.platform, 'v3qual')
                self.recorder = OperationalQualification(
                    namespace, self.clock, self.device_id, self.release_getter
                )
            else:
                self.recorder = self.recorder_factory(
                    self.clock, self.device_id, self.release_getter
                )
            self.recorder.start()
            self.error = ''
            return True
        except Exception as exc:
            self.recorder = None
            self.platform = None
            detail = str(exc)[:160] or exc.__class__.__name__
            if detail == 'native v3 platform is unavailable':
                detail = (
                    'matching v3 core firmware is unavailable; install the '
                    'universal release, not the application-only package'
                )
            self.error = detail
            return False

    def observe(self, health_state, storage_free_bytes, network_up,
                canary_paused=False):
        if not self.start():
            return None
        try:
            return self.recorder.sample(
                health_state, storage_free_bytes, network_up, canary_paused
            )
        except Exception as exc:
            self.error = str(exc)[:160] or exc.__class__.__name__
            return None

    def record_update(self, outcome):
        if not self.start():
            return False
        try:
            self.recorder.record_update(outcome)
            return True
        except Exception as exc:
            self.error = str(exc)[:160] or exc.__class__.__name__
            return False

    def snapshot(self):
        if not self.start():
            return None
        try:
            return self.recorder.snapshot()
        except Exception as exc:
            self.error = str(exc)[:160] or exc.__class__.__name__
            return None

    def status(self):
        evidence = self.snapshot()
        if evidence is None:
            return {
                'available': False, 'summary': 'Unavailable',
                'error': self.error, 'evidence': None,
            }
        counts = {
            'passed': 0, 'failed': 0, 'in-progress': 0, 'not-run': 0,
        }
        for gate in evidence.get('gates', ()):
            state = str(gate.get('status', 'not-run'))
            if state in counts:
                counts[state] += 1
        summary = (
            'Ready' if evidence.get('promotion_ready') else
            ('Blocked' if counts['failed'] else
             ('In progress' if counts['in-progress'] else 'Not started'))
        )
        return {
            'available': True, 'summary': summary, 'error': '',
            'counts': counts, 'evidence': evidence,
            'native_update': self._native_update_status(),
        }

    def _native_update_status(self):
        if self.platform is None:
            return None
        try:
            capabilities = self.platform.capabilities()
            updates = capabilities['updates']
            snapshot = self.platform.update_snapshot()
            return {
                'available': bool(updates['native_trial_observation']),
                'control_available': bool(
                    updates['native_trial_control']
                ),
                'paired_trial_qualified': bool(
                    updates['paired_trial']
                ),
                'native_rollback_qualified': bool(
                    updates['native_rollback']
                ),
                'recovery_available': bool(
                    capabilities['recovery']['product_independent']
                ),
                'recovery_qualified': bool(
                    capabilities['recovery']['qualified']
                ),
                'jobs_available': bool(
                    capabilities['jobs']['async_worker']
                ),
                'jobs_qualified': bool(capabilities['jobs']['qualified']),
                'snapshot': snapshot,
                'recovery': self.platform.recovery_snapshot(),
            }
        except Exception as exc:
            return {
                'available': False, 'error':
                (str(exc)[:160] or exc.__class__.__name__),
            }

    async def monitor(self, health_getter, storage_getter, network_getter,
                      canary_getter, sleep, interval_s=60):
        while True:
            try:
                network_up = bool(network_getter())
            except Exception:
                network_up = False
            try:
                health_state = health_getter()
            except Exception:
                health_state = None
            try:
                storage = storage_getter() or {}
                storage_free = storage.get('free_bytes')
                if (not isinstance(storage_free, int) or
                        isinstance(storage_free, bool) or storage_free < 0):
                    storage_free = None
            except Exception:
                storage_free = None
            try:
                canary_paused = bool(canary_getter())
            except Exception:
                canary_paused = False
            self.observe(
                health_state, storage_free, network_up, canary_paused
            )
            await sleep(interval_s)

    @staticmethod
    def observation(main_error, module_issues, storage, canary_paused):
        storage_free = (storage or {}).get('free_bytes')
        if (not isinstance(storage_free, int) or
                isinstance(storage_free, bool) or storage_free < 0):
            storage_free = None
        return {
            'health_state': (
                'failed' if main_error else
                ('degraded' if module_issues else 'healthy')
            ),
            'storage_free_bytes': storage_free,
            'canary_paused': bool(canary_paused),
        }


def runtime_qualification_service(device_id, versions, application, firmware,
                                  universal, clock):
    def release():
        return {
            'version': versions.PRODUCT_VERSION,
            'sequence': max(
                application.running_release_sequence(),
                firmware.running_release_sequence()
            ),
            'confirmed': (
                application.update_status().get('status', 'idle') == 'idle' and
                firmware.update_status().get('status', 'idle') == 'idle' and
                universal.update_status().get('status', 'idle') in
                ('idle', 'confirmed')
            ),
        }
    return AlphaQualificationService(device_id, release, clock)
