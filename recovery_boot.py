"""Boot supervisor for A/B Python application slots and firmware rollback."""


try:
    import ujson as json
except ImportError:
    import json

try:
    import uos as os
except ImportError:
    import os

import device_config


RECOVERY_API_VERSION = 6
CORE_API_VERSION = 9
TRIAL_DEADLINE_MS = 180000
RECOVERY_STATE_PATH = '.recovery-state.json'
MAX_UNHEALTHY_BOOTS = 2
_trial_timer = None


def _reset():
    try:
        import machine
        machine.reset()
    except Exception:
        pass


def _replace(source, target):
    try:
        os.remove(target)
    except OSError:
        pass
    os.rename(source, target)


def _read_recovery_state():
    try:
        with open(RECOVERY_STATE_PATH, 'r') as stream:
            state = json.load(stream)
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def _write_recovery_state(state):
    temp = RECOVERY_STATE_PATH + '.tmp'
    with open(temp, 'w') as stream:
        json.dump(state, stream)
    _replace(temp, RECOVERY_STATE_PATH)


def clear_recovery_request():
    try:
        os.remove(RECOVERY_STATE_PATH)
        return True
    except OSError:
        return False


def request_recovery(reason='Application startup failed'):
    current = _read_recovery_state()
    _write_recovery_state({
        'mode': 'recovery',
        'reason': str(reason)[:240],
        'failures': int(current.get('failures', 0) or 0),
        'pending': False,
    })
    return True


def _remove_user_file(path):
    try:
        os.stat(path)
    except OSError:
        return False
    os.remove(path)
    return True


def _complete_factory_reset(app_update, certificate_manager, credential_store,
                            firmware_update):
    """Finish a portal-requested reset in the immutable recovery layer."""
    if not credential_store.factory_reset_pending():
        return False
    app_state = app_update.update_status()
    if app_state.get('status') == 'ready':
        app_update.discard_pending_update()
    elif app_state.get('status') in ('trial', 'committing', 'activating'):
        app_update.rollback_update()
    if firmware_update.update_status().get('status') == 'ready':
        firmware_update.discard_pending_update()
    certificate_manager.clear_certificate_state()
    module_path = device_config.MODULE_SETTINGS_FILE
    for path in (
        module_path, module_path + '.previous', module_path + '.tmp',
        module_path + '.copying', '.update-history.json',
        '.runtime-health.json', '.paired-update-state.json',
        '.universal-update-state.json', '.universal-update-state.json.tmp'
    ):
        _remove_user_file(path)
    clear_recovery_request()
    credential_store.complete_factory_reset()
    return True


def mark_application_healthy():
    clear_recovery_request()
    return cancel_trial_deadline_if_healthy()


def _prepare_boot_attempt():
    state = _read_recovery_state()
    if state.get('mode') == 'recovery':
        return str(state.get('reason', 'Application startup failed'))
    failures = int(state.get('failures', 0) or 0)
    if state.get('pending'):
        failures += 1
    if failures >= MAX_UNHEALTHY_BOOTS:
        reason = 'Application did not reach its startup health check after ' + str(failures) + ' boots'
        request_recovery(reason)
        return reason
    _write_recovery_state({
        'mode': 'booting',
        'reason': str(state.get('reason', ''))[:240],
        'failures': failures,
        'pending': True,
    })
    return ''


def _recovery_ap_name():
    try:
        import hardware_platform
        try:
            import ubinascii as binascii
        except ImportError:
            import binascii
        suffix = binascii.hexlify(hardware_platform.unique_id()).decode()[-6:]
    except Exception:
        suffix = 'device'
    return 'IoTMD-Recovery-' + suffix


def _setup_ap_name():
    return _recovery_ap_name().replace('IoTMD-Recovery-', 'IoTMD-Setup-', 1)


def _run_initial_setup():
    import credential_store
    import hardware_platform
    import setup_wizard
    try:
        import uasyncio as asyncio
    except ImportError:
        import asyncio
    password = credential_store.bootstrap_key()
    if len(password) < credential_store.MIN_PASSWORD_LENGTH:
        raise RuntimeError(
            'first boot requires a unique factory setup key in encrypted NVS; '
            'refusing to start an unsecured setup access point'
        )
    status_led = hardware_platform.status_output(
        device_config.STATUS_LED_PIN, device_config.STATUS_LED_TYPE
    )
    hardware_platform.set_status_led_state(status_led, 'setup')

    async def serve():
        await setup_wizard.serve(
            _setup_ap_name(), password, hardware_platform.reset
        )

    asyncio.run(serve())


def _run_core_recovery(reason):
    import credential_store
    import hardware_platform
    import wifi_recovery
    try:
        import uasyncio as asyncio
    except ImportError:
        import asyncio
    config = credential_store.load(require_provisioned=True)
    password = config['recovery']['ap_password']
    password_verifier = config['recovery']['password_verifier']
    if len(str(password)) < credential_store.MIN_PASSWORD_LENGTH:
        raise RuntimeError(
            'core recovery requested but encrypted recovery AP credentials are invalid; use USB recovery'
        )
    if not password_verifier:
        raise RuntimeError(
            'core recovery requested but encrypted console credentials are invalid; use USB recovery'
        )
    status_led = hardware_platform.status_output(38, 'neopixel')
    hardware_platform.set_status_led_state(status_led, 'recovery')

    async def serve():
        await wifi_recovery.serve_core_recovery(
            _recovery_ap_name(), password, password_verifier, reason,
            clear_recovery_request, hardware_platform.reset,
            timeout_s=wifi_recovery.recovery_timeout()
        )

    asyncio.run(serve())


def _start_trial_deadline():
    global _trial_timer
    try:
        from machine import Timer
        try:
            import universal_update
            deadline_ms = universal_update.trial_timeout_ms(TRIAL_DEADLINE_MS)
        except Exception:
            deadline_ms = TRIAL_DEADLINE_MS
        _trial_timer = Timer(-1)
        _trial_timer.init(
            mode=Timer.ONE_SHOT,
            period=deadline_ms,
            callback=lambda timer: _reset()
        )
        return True
    except Exception:
        _trial_timer = None
        return False


def cancel_trial_deadline():
    global _trial_timer
    if _trial_timer is None:
        return False
    try:
        _trial_timer.deinit()
    except Exception:
        pass
    _trial_timer = None
    return True


def cancel_trial_deadline_if_healthy():
    try:
        import app_update
        import firmware_update
        app_trial = app_update.update_status().get('status') in ('trial', 'committing')
        firmware_trial = firmware_update.update_status().get('status') == 'trial'
        if not app_trial and not firmware_trial:
            return cancel_trial_deadline()
    except Exception:
        pass
    return False


def run():
    import app_update
    import certificate_manager
    import credential_store
    import firmware_update
    import hardware_platform
    import universal_update

    status_led = hardware_platform.status_output(38, 'neopixel')
    hardware_platform.set_status_led_state(status_led, 'boot')

    if _complete_factory_reset(
        app_update, certificate_manager, credential_store, firmware_update
    ):
        _run_initial_setup()
        return

    cleanup = getattr(app_update, 'cleanup_interrupted', None)
    if cleanup:
        cleanup()
    cleanup = getattr(firmware_update, 'cleanup_interrupted', None)
    if cleanup:
        cleanup()
    cleanup = getattr(universal_update, 'cleanup_interrupted', None)
    if cleanup:
        cleanup()
    certificate_manager.recover_certificate_transaction()
    firmware_state = firmware_update.boot_status() or {}
    if firmware_state.get('status') == 'rolled_back':
        clear_recovery_request()

    if not credential_store.is_provisioned():
        _run_initial_setup()
        return

    network_trial = credential_store.prepare_network_trial_boot()
    if network_trial == 'rolled_back':
        clear_recovery_request()
        _reset()
        return

    recovery_reason = _prepare_boot_attempt()
    if recovery_reason:
        _run_core_recovery(recovery_reason)
        return

    try:
        activation_result = app_update.activate_pending()
        if 'rolled back' in str(activation_result):
            clear_recovery_request()
            _prepare_boot_attempt()
    except Exception as exc:
        try:
            import update_support
            state = app_update.update_status()
            update_support.record_update_event(
                'application', 'activation_failed', state.get('version', ''),
                detail=str(exc)
            )
        except Exception:
            pass
        app_update.rollback_update()

    # Guard every application startup, not only update trials. A hung application
    # is reset and repeated unhealthy boots enter the frozen recovery console.
    _start_trial_deadline()

    app_update.prepare_application_path()
    entry = app_update.application_entry()
    namespace = {'__name__': '__main__', '__file__': entry}
    try:
        with open(entry, 'r') as stream:
            source = stream.read()
        exec(source, namespace)
    except Exception as exc:
        try:
            handler = namespace.get('set_main_device_error')
            if handler:
                handler()
        except Exception:
            pass
        reset_required = firmware_update.update_status().get('status') == 'trial'
        if app_update.update_status().get('status') in (
            'activating', 'trial', 'committing'
        ):
            app_update.rollback_update()
            reset_required = True
        if reset_required:
            clear_recovery_request()
            _reset()
            return
        request_recovery('Application exception: ' + str(exc))
        _reset()
        return

    if (
        app_update.update_status().get('status') in ('trial', 'committing') or
        firmware_update.update_status().get('status') == 'trial'
    ):
        if app_update.update_status().get('status') in ('trial', 'committing'):
            app_update.rollback_update()
            clear_recovery_request()
        _reset()
    else:
        state = _read_recovery_state()
        if state.get('mode') == 'recovery':
            _reset()
        else:
            request_recovery('Application exited before completing normal operation')
            _reset()
