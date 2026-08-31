"""Local boot-health gates and paired update confirmation."""

from application.boot_health import evaluate


class StartupService:
    def __init__(self, platform, boot, lifecycle, health, log_output):
        self.platform = platform
        self.boot = boot
        self.lifecycle = lifecycle
        self.health = health
        self.log_output = log_output

    def start_watchdog(self, factory, timeout_ms, progress_callback=None,
                       progress_setter=None):
        if not timeout_ms:
            return None, True
        if factory is None:
            return None, False
        timeout_ms = self.platform.watchdog_timeout(timeout_ms)
        watchdog = factory(timeout=timeout_ms)
        if progress_setter and progress_callback:
            progress_setter(progress_callback)
        self.log_output(
            'Local', 'Watchdog',
            {'log': 'Enabled: ' + str(timeout_ms) + ' ms'}, 'INFO'
        )
        return watchdog, True

    def check(self, free_heap, minimum_free_heap, required_services,
              service_states, watchdog_required=False, watchdog_ready=False):
        self.boot.stage('essential-services', device_state='initialising')
        result = evaluate(
            self.platform.capabilities(), free_heap, minimum_free_heap,
            required_services, service_states, watchdog_required, watchdog_ready
        )
        self.boot.stage('health-check', durable=True)
        if result['healthy']:
            return result
        detail = '; '.join(result['failures'])
        self.lifecycle.transition('failed', detail)
        self.health.record_event(
            'activation_health_failed', detail, result,
            force=True, severity='critical', component='startup'
        )
        self.boot.fail(detail)
        self.log_output(
            'Local', 'Update health',
            {'log': 'Activation health check failed: ' + detail}, 'ERROR'
        )
        return result

    def confirm_updates(self, firmware_update, app_update, universal_update,
                        recovery_boot):
        firmware_confirmed = False
        application_confirmed = False
        try:
            if firmware_update.confirm_update():
                firmware_confirmed = True
                self.log_output(
                    'Local', 'Base firmware',
                    {'log': 'OTA partition confirmed after local health check'},
                    'INFO'
                )
        except Exception as exc:
            self.log_output(
                'Local', 'Base firmware',
                {'log': 'Could not confirm OTA partition - ' + str(exc)}, 'ERROR'
            )
        if app_update.confirm_update():
            application_confirmed = True
            self.log_output(
                'Local', 'Application update',
                {'log': 'Update confirmed healthy'}, 'INFO'
            )
        if universal_update.confirm_update():
            self.log_output(
                'Local', 'Universal update',
                {'log': 'Core and application update confirmed healthy'}, 'INFO'
            )
        marker = getattr(recovery_boot, 'mark_application_healthy', None)
        if marker:
            marker()
        return firmware_confirmed, application_confirmed

    def finalise(self, state, ntp_ready, api_enabled, api_server,
                 mqtt_configured, mqtt_started):
        self.lifecycle.transition('running')
        state.set('phase', 'running')
        degraded = []
        if not ntp_ready:
            degraded.append('NTP unavailable')
        if api_enabled and api_server is None:
            degraded.append('Device API unavailable')
        if mqtt_configured and not mqtt_started:
            degraded.append('MQTT unavailable')
        if degraded:
            reason = '; '.join(degraded)
            self.lifecycle.degrade(reason)
            self.boot.degrade(reason)
            return 'degraded'
        self.boot.healthy()
        return 'running'
