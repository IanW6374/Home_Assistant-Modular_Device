import app_update
import firmware_update


firmware_update.boot_status()


try:
    app_update.activate_pending()
except Exception:
    app_update.rollback_update()

try:
    exec(open('HA-Device.py').read())
except Exception:
    reset_required = firmware_update.update_status().get('status') == 'trial'
    if app_update.update_status().get('status') == 'trial':
        app_update.rollback_update()
        reset_required = True
    if reset_required:
        try:
            import machine
            machine.reset()
        except Exception:
            pass
    raise

if (
    app_update.update_status().get('status') == 'trial' or
    firmware_update.update_status().get('status') == 'trial'
):
    if app_update.update_status().get('status') == 'trial':
        app_update.rollback_update()
    try:
        import machine
        machine.reset()
    except Exception:
        pass
