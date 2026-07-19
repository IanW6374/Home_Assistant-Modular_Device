"""Boot supervisor for A/B Python application slots and firmware rollback."""


RECOVERY_API_VERSION = 2
TRIAL_DEADLINE_MS = 180000
_trial_timer = None


def _reset():
    try:
        import machine
        machine.reset()
    except Exception:
        pass


def _start_trial_deadline():
    global _trial_timer
    try:
        from machine import Timer
        _trial_timer = Timer(-1)
        _trial_timer.init(
            mode=Timer.ONE_SHOT,
            period=TRIAL_DEADLINE_MS,
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
    import firmware_update

    cleanup = getattr(app_update, 'cleanup_interrupted', None)
    if cleanup:
        cleanup()
    cleanup = getattr(firmware_update, 'cleanup_interrupted', None)
    if cleanup:
        cleanup()
    firmware_update.boot_status()

    try:
        app_update.activate_pending()
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

    if (
        app_update.update_status().get('status') in ('trial', 'committing') or
        firmware_update.update_status().get('status') == 'trial'
    ):
        _start_trial_deadline()

    app_update.prepare_application_path()
    entry = app_update.application_entry()
    namespace = {'__name__': '__main__', '__file__': entry}
    try:
        with open(entry, 'r') as stream:
            source = stream.read()
        exec(source, namespace)
    except Exception:
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
            _reset()
        raise

    if (
        app_update.update_status().get('status') in ('trial', 'committing') or
        firmware_update.update_status().get('status') == 'trial'
    ):
        if app_update.update_status().get('status') in ('trial', 'committing'):
            app_update.rollback_update()
        _reset()
    else:
        cancel_trial_deadline()
