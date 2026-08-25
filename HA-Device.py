import ssl
import time
try:
    import uos as os
except ImportError:
    import os
try:
    import gc
except ImportError:
    gc = None
from binascii import hexlify
import json
import credential_security
import credential_store
import app_update
import firmware_update
import universal_update
import hardware_platform
import recovery_boot
import update_security
import update_support
import wifi_recovery
import release_update
import update_orchestrator
import timezone_rules
import component_versions
import certificate_manager
import configuration_manager
import api_security
import portal_auth
import fleet_management
import support_bundle
import resumable_upload
from remote_logging import RemoteSyslog
from device_api import DeviceAPI, start_device_api
from runtime_health import HealthHistory
from message_broker import BoundedPublishQueue, ModuleBroker
from services.event_service import EventService
from services.event_sinks import LegacyLogSink
from services.module_runtime import ModuleRuntime
from services.network_service import NetworkService
from services.messaging_service import MessagingService
from services.home_assistant_service import HomeAssistantService
from services.portal_service import PortalService
from services.update_service import UpdateService
from portal_contracts import PortalDependencies
from portal_view_models import module_summaries as build_module_summaries
from application import ApplicationContext, RuntimeState
import settings_loader as device_settings
try:
    import network
except ImportError:
    network = None
try:
    from machine import WDT
except ImportError:
    WDT = None
try:
    from machine import Timer
except ImportError:
    Timer = None
from primitives import Encoder
from mqtt_as import MQTTClient, config
import asyncio
from device_modules import setup_device
from device_modules import loader as driver_loader
from device_modules.loader import (
    configure_for_devices, configured_driver_names, device_types_for_devices,
    get_device_types
)
from device_modules.driver_index import DRIVER_VERSIONS
from device_modules.base import (
    ha_availability_topic,
    ha_config_topic,
    ha_device_topic,
    ha_set_topic,
    ha_state_topic,
    ha_safe_id,
    ha_unique_id,
    handle_local_input,
    homeassistant_device_info,
    homeassistant_origin_info,
    module_diagnostics_need_attention
)
from device_modules.validation import validate_device_config
from device_modules.logging import set_log_output
from web_portal import start_web_portal
from display import LocalDisplayService

try:
    import ntptime
except ImportError:
    ntptime = None


def cancel_recovery_trial_deadline_if_healthy():
    """Cancel the recovery watchdog when supported by the base firmware.

    Application bundles can be installed before the corresponding frozen
    recovery firmware.  Older recovery_boot modules did not expose the health
    aware cancellation helper, so treat its absence as a legacy no-op instead
    of preventing the application from starting.
    """
    cancel = getattr(recovery_boot, 'cancel_trial_deadline_if_healthy', None)
    if cancel:
        return cancel()
    return False



# Local configuration

mqtt_ca_cert_path = device_settings.service_ca_path('mqtt')
release_ca_cert_path = device_settings.service_ca_path('release')
runtime_credentials = credential_store.load(require_provisioned=True)

config['ssid'] = runtime_credentials['wifi']['ssid']
config['wifi_pw'] = runtime_credentials['wifi']['password']


config['server'] = runtime_credentials['mqtt']['server']
config['port'] = runtime_credentials['mqtt']['port']
config['user'] = runtime_credentials['mqtt']['username']
config['password'] = runtime_credentials['mqtt']['password']
config['ssl'] = runtime_credentials['mqtt']['ssl']
mqtt_configured = runtime_credentials['mqtt'].get('configured') is True

ha_discovery = device_settings.ha_discovery
ha_devicename = runtime_credentials['device_name']
moduleSettingsFile = device_settings.module_settings_file


# Module settings

hardware_deviceid = hexlify(hardware_platform.unique_id()).decode()
deviceid = hardware_deviceid + '_' + ha_safe_id(ha_devicename)

ntp_servers = device_settings.ntp_servers
timezone_offset_minutes = device_settings.timezone_offset_minutes
timezone_name = device_settings.timezone_name
ha_system_diagnostics = device_settings.ha_system_diagnostics

loglevels = ['ERROR', 'INFO', 'DEBUG']
loglevel = device_settings.loglevel
watchdog_timeout_ms = device_settings.watchdog_timeout_ms
watchdog = None
ntp_synced = False
web_portal_server = None
device_api_server = None
scheduled_control_timer = None
web_portal_enabled = device_settings.web_portal_enabled
web_portal_host = device_settings.web_portal_host
web_portal_username = runtime_credentials['portal']['username']
web_portal_password_verifier = runtime_credentials['portal']['password_verifier']
web_portal_password_change_required = False
web_portal_cert_path = device_settings.web_portal_cert_path
web_portal_updates_enabled = device_settings.web_portal_updates_enabled
web_portal_update_max_bytes = device_settings.web_portal_update_max_bytes
web_portal_allow_protected_updates = device_settings.web_portal_allow_protected_updates
web_portal_firmware_updates_enabled = device_settings.web_portal_firmware_updates_enabled
web_portal_firmware_update_max_bytes = device_settings.web_portal_firmware_update_max_bytes
web_portal_key_path = device_settings.web_portal_key_path
web_portal_transport = runtime_credentials['portal'].get('transport', 'auto')
device_api_config = runtime_credentials.get('api', {
    'enabled': False, 'port': device_settings.device_api_port, 'auth': 'mtls'
})
device_api_enabled = device_api_config.get('enabled') is True
device_api_port = int(device_api_config.get('port', device_settings.device_api_port))
api_client_registry = api_security.ClientRegistry(
    device_settings.api_client_registry_path
)
api_client_ca_store = api_security.CATrustStore(
    device_settings.api_client_ca_directory
)


def portal_certificates_installed():
    try:
        return (
            os.stat(web_portal_cert_path)[6] > 0 and
            os.stat(web_portal_key_path)[6] > 0
        )
    except OSError:
        return False


web_portal_https = (
    web_portal_transport == 'https' or
    (web_portal_transport == 'auto' and portal_certificates_installed())
)
web_portal_port = runtime_credentials['portal'].get('port')
if web_portal_port is None:
    web_portal_port = device_settings.web_portal_port
if web_portal_port is None:
    web_portal_port = 8443 if web_portal_https else 8080
web_portal_log_refresh_s = device_settings.web_portal_log_refresh_s
web_portal_value_refresh_s = device_settings.web_portal_value_refresh_s
wifi_recovery_enabled = device_settings.wifi_recovery_enabled
wifi_recovery_timeout_s = device_settings.wifi_recovery_timeout_s
network_trial_timeout_s = device_settings.network_trial_timeout_s
release_manifest_url = device_settings.release_manifest_url
release_channel = runtime_credentials['release']['channel']
certificate_config = runtime_credentials.get('certificate', {'mode': 'manual'})
if network is not None and certificate_config.get('hostname'):
    certificate_manager.configure_network_hostname(certificate_config['hostname'])
if network is not None and hasattr(credential_store, 'configure_station'):
    wlan_class = network.WLAN
    station_interface = getattr(
        wlan_class, 'IF_STA', getattr(network, 'STA_IF', 0)
    )
    credential_store.configure_station(
        wlan_class(station_interface), runtime_credentials['wifi']
    )
release_check_schedule = device_settings.release_check_schedule
release_check_time = device_settings.release_check_time
release_check_weekday = device_settings.release_check_weekday
release_auto_download = device_settings.release_auto_download
release_auto_activate = device_settings.release_auto_activate
web_portal_session_timeout_s = device_settings.web_portal_session_timeout_s
release_available = {}
release_check_status = 'Not checked'
release_last_checked = ''
release_automatic_check_status = 'Not checked'
release_automatic_last_checked = ''
web_log_buffer_lines = device_settings.web_log_buffer_lines
web_log_line_max_chars = device_settings.web_log_line_max_chars
log_buffer = []
audit_log_buffer = []
remote_syslog = RemoteSyslog(
    runtime_credentials.get('syslog', {}), ha_devicename,
    device_settings.syslog_ca_path,
    status_callback=lambda severity, message: logOutput(
        'Local', 'Remote syslog',
        {'log': message, 'force': True, 'skip_remote_syslog': True}, severity
    )
)
local_display_config = device_settings.local_display
local_display_service = None
last_discovery_count = 0
main_device_error = False
failedModules = []
pending_configuration_import = None
pending_secure_configuration_import = None
pending_restart_reasons = []


def ticks_ms():
    if hasattr(time, 'ticks_ms'):
        return time.ticks_ms()
    return int(time.time() * 1000)


def ticks_diff(end, start):
    if hasattr(time, 'ticks_diff'):
        return time.ticks_diff(end, start)
    return end - start


def wall_time_text(epoch=None):
    current = timezone_rules.localtime(epoch, name=timezone_name)
    return "{:04}-{:02}-{:02} {:02}:{:02}:{:02}".format(
        current[0], current[1], current[2],
        current[3], current[4], current[5]
    )


def modules_have_issues():
    """Return True when any loaded module reports an attention state."""
    if failedModules:
        return True
    for device_char in outputDevices:
        if device_char.get('uuid') == '0000':
            continue
        driver = device_char.get('driver')
        if not driver or not hasattr(driver, 'diagnostics_payload'):
            continue
        try:
            diagnostics = driver.diagnostics_payload() or {}
        except Exception:
            return True

        if module_diagnostics_need_attention(diagnostics):
            return True
    return False


def set_status_led_colour(output, colour):
    if hasattr(output, 'set_colour'):
        output.set_colour(colour)


def set_main_device_error():
    """Latch the main-device fault state and show it immediately."""
    global main_device_error
    main_device_error = True
    try:
        status_led = outputDevices[0]['output']['0']
        set_status_led_colour(status_led, hardware_platform.STATUS_COLOUR_ERROR)
        status_led(1)
    except Exception:
        pass


def service_password_calculation(active):
    """Keep the watchdog alive and expose long authentication work on the LED."""
    if watchdog:
        watchdog.feed()
    try:
        status_led = outputDevices[0]['output']['0']
        if active:
            hardware_platform.set_status_led_state(status_led, 'boot')
        else:
            colour, _ = hardware_platform.status_led_mode(
                main_device_error, modules_have_issues()
            )
            set_status_led_colour(status_led, colour)
            status_led(1)
    except Exception:
        pass


boot_ms = ticks_ms()

# Device types will be loaded from device modules
deviceTypes = []

deviceObjects = [
    # System LED
    {'name': 'S1', 'uuid': '0000', 'type': {'class': 'light', 'subclass': 'onoff'}, 'entities': {'0': {'state': 'OFF'}}, 'gpio': {'activeHigh': True, 'output': {'0': 'LED'}}},
]

outputDevices = [
    # System LED
    {'uuid': '0000', 'index': 0, 'output': {'0': hardware_platform.status_output(device_settings.status_led_pin, device_settings.status_led_type)}}
]

inputDevices = []
runtime_health = HealthHistory()
fleet_service = fleet_management.FleetService(
    hardware_deviceid, 'default',
    now=lambda: int(time.time()),
    localtime=lambda epoch: timezone_rules.localtime(epoch, timezone_name)
)


def reclaim_resumable_update_storage(kind, _required):
    """Sacrifice only the inactive application generation for a `.hamu`."""
    if str(kind) != 'universal':
        return False
    reclaimed = app_update.reclaim_inactive_slot()
    if reclaimed:
        update_support.record_update_event(
            'application', 'reclaimed',
            detail='inactive slot reclaimed for universal upload'
        )
    return reclaimed


resumable_update_store = resumable_upload.ResumableUploadStore(
    maximum_bytes=(
        web_portal_update_max_bytes + web_portal_firmware_update_max_bytes + 8192
    ),
    storage_reclaimer=reclaim_resumable_update_storage
)
runtime_health.record_boot(hardware_platform.reset_cause())
saved_release_check = runtime_health.snapshot().get('observations', {}).get(
    'last_release_check', {}
)
if isinstance(saved_release_check, dict) and saved_release_check.get('status'):
    release_automatic_check_status = str(saved_release_check.get('status'))
    release_automatic_last_checked = wall_time_text(saved_release_check.get('time'))
mqtt_publish_queue = BoundedPublishQueue(state_limit=64, critical_limit=96)
module_broker = ModuleBroker(lambda: outputDevices + inputDevices)
event_service = EventService(runtime_health)
module_runtime = ModuleRuntime(module_broker, driver_loader)
portal_service = PortalService(start_web_portal)


def _critical_task_failure(name, exc):
    detail = str(name) + ': ' + (str(exc) or exc.__class__.__name__)
    runtime_health.observe('last_startup_exception', detail, force=True)
    application_context.lifecycle.transition('failed', detail)
    logOutput('Local', 'Task', {'log': detail + ' stopped'}, 'ERROR')
    set_main_device_error()


application_context = ApplicationContext(
    {
        'device_id': hardware_deviceid,
        'runtime_id': deviceid,
        'device_name': ha_devicename,
        'board': hardware_platform.platform_id(),
    },
    configuration=device_settings,
    state=RuntimeState({
        'phase': 'initialising',
        'network': 'offline',
        'portal': 'stopped',
        'api': 'stopped',
        'mqtt': 'stopped',
    }),
    event_service=event_service,
    critical_failure=_critical_task_failure,
)
application_context.register('events', event_service)
application_context.register('modules', module_runtime)
application_context.register('portal', portal_service)



# Function:  Validate UUID
def validUUID(uuid):
    if any(device['uuid'] == uuid for device in deviceObjects):
        return False

    if len(uuid) != 4:
        return False

    try:
        int(uuid, 16)
        return True
    except ValueError:
        return False


def find_device_type(device):
    return next((t for t in deviceTypes
                 if t['class'] == device['type']['class']
                 and device['type']['subclass'] in t['subclass']), None)



# Function:  Validate device import
def deviceValidation (device):
    
    validationError = False
    
    if not validUUID(device['uuid']):
        
        logOutput ('Local', 'Add device', {'log':'Failed to create device - ' + device['name'] + ' - Invalid UUID'}, 'ERROR')     
        validationError = True    


    type_entry = find_device_type(device)
    if type_entry is None:
        class_supported = any(t['class'] == device['type']['class'] for t in deviceTypes)
        if class_supported:
            logOutput ('Local', 'Add device', {'log':'Failed to create device - ' + device['name'] + ' - Device subclass "' + device['type']['subclass'] + '" not Supported'}, 'ERROR')
        else:
            logOutput ('Local', 'Add device', {'log':'Failed to create device - ' + device['name'] + ' - Device class "' + device['type']['class'] +'" not Supported'}, 'ERROR')
        return False

    if device['type']['class'] == 'sensor':
        supported_entities = type_entry['subclass'][device['type']['subclass']]['entities']
        for e in device['entities']:
            entity_class = device['entities'][str(e)]['class']
            if entity_class not in supported_entities:
                logOutput ('Local', 'Add device', {'log':'Failed to create device - ' + device['name'] + ' - Device entity "' + entity_class + '" not Supported'}, 'ERROR')
                validationError = True

                
    return not validationError




class Style():
  ERROR = "\033[31m"
  RESET = "\033[0m"



# Function:  Log Output       
def logOutput(mode, action, data, logtype):
    utc_time = time.localtime()
    current_time = timezone_rules.localtime(name=timezone_name)
    
    timestamp = "{:04}{:02}{:02} {:02}{:02}{:02}".format(current_time[0], current_time[1], current_time[2], current_time[3], current_time[4], current_time[5])
    
    is_audit = data.get('audit') is True
    if is_audit or data.get('force') or loglevels.index(logtype) <= loglevels.index(loglevel):
        
        log = timestamp + '  ' + mode + ': ' + action + ' - ' + data['log']
        
        if mode == 'MQTT' and loglevel == 'DEBUG' and action != 'Connect':
            topic = data.get('topic')
            payload = data.get('payload')
            if topic is not None:
                log += '\n\n\tTopic: ' + str(topic)
            if 'payload' in data:
                log += '\n\tPayload: ' + json.dumps(payload)
            if topic is not None or 'payload' in data:
                log += '\n'
                   
        if logtype == 'ERROR':
            
            print (f'{Style.ERROR}' + log + f'{Style.RESET}')
            
        else:
            
            print (log)

        if is_audit:
            remember_audit_log(log)
        else:
            remember_log(log)
        if not data.get('skip_remote_syslog'):
            remote_syslog.enqueue(
                '{:04}-{:02}-{:02}T{:02}:{:02}:{:02}'.format(
                    utc_time[0], utc_time[1], utc_time[2],
                    utc_time[3], utc_time[4], utc_time[5]
                ),
                log, logtype, audit=is_audit
            )


event_service.add_sink(LegacyLogSink(logOutput))


def publish_logtype(msg):
    if 'logtype' in msg:
        return msg['logtype']

    log = msg.get('log', '')
    if log.startswith('HA Update:'):
        return 'DEBUG'
    if log.startswith('HA Discovery cleanup:'):
        return 'DEBUG'
    if log.startswith('HA Discovery entity:'):
        return 'DEBUG'
    return 'INFO'


def remember_log(log):
    if len(log) > web_log_line_max_chars:
        log = log[:web_log_line_max_chars] + '...'
    log_buffer.append(log)
    while len(log_buffer) > web_log_buffer_lines:
        log_buffer.pop(0)


def get_log_buffer():
    return list(log_buffer)


def remember_audit_log(log):
    if len(log) > web_log_line_max_chars:
        log = log[:web_log_line_max_chars] + '...'
    audit_log_buffer.append(log)
    while len(audit_log_buffer) > web_log_buffer_lines:
        audit_log_buffer.pop(0)


def get_audit_log_buffer():
    return list(audit_log_buffer)


def get_loglevel():
    return loglevel


def set_loglevel(level):
    global loglevel
    if level in loglevels:
        loglevel = level
        MQTTClient.DEBUG = loglevel == 'DEBUG'
        try:
            current = credential_store.public_settings()
            if current.get('loglevel') != level:
                credential_store.update_operational_settings({'loglevel': level})
        except Exception:
            pass


def set_log_buffer_lines(line_count):
    global web_log_buffer_lines
    line_count = int(line_count)
    if not 0 <= line_count <= 500:
        raise ValueError('log entry limit must be between 0 and 500')
    web_log_buffer_lines = line_count
    while len(log_buffer) > web_log_buffer_lines:
        log_buffer.pop(0)
    while len(audit_log_buffer) > web_log_buffer_lines:
        audit_log_buffer.pop(0)
    try:
        current = credential_store.public_settings()
        if current.get('log_buffer_lines') != line_count:
            credential_store.update_operational_settings({
                'log_buffer_lines': line_count
            })
    except Exception:
        pass
    return web_log_buffer_lines


portal_tasks = {}


def start_task(name, coroutine, main_device_task=False):
    return application_context.tasks.start(
        name, coroutine, critical=main_device_task
    )


def _schedule_hardware_action(name, action, label, delay_ms=8000):
    global scheduled_control_timer
    def perform(_timer=None):
        action()
    if Timer is not None:
        try:
            scheduled_control_timer = Timer(-1)
            scheduled_control_timer.init(
                mode=Timer.ONE_SHOT, period=max(1, int(delay_ms)), callback=perform
            )
            return
        except Exception as exc:
            logOutput(
                'Local', label, {'log': 'Hardware timer unavailable; using event loop - ' +
                 str(exc)}, 'ERROR'
            )
    async def delayed_action():
        if hasattr(asyncio, 'sleep_ms'):
            await asyncio.sleep_ms(max(1, int(delay_ms)))
        else:
            await asyncio.sleep(max(1, int(delay_ms)) / 1000)
        perform()
    start_task(name, delayed_action())
def schedule_hardware_reset(name, delay_ms=8000):
    _schedule_hardware_action(name, hardware_platform.reset, 'Reset', delay_ms)
def _shutdown_hardware():
    try:
        outputDevices[0]['output']['0'](0)
    except Exception: pass
    hardware_platform.shutdown()
def schedule_hardware_shutdown(name, delay_ms=8000):
    _schedule_hardware_action(name, _shutdown_hardware, 'Shutdown', delay_ms)
def mark_restart_required(reason):
    reason = str(reason or 'Configuration changed')
    if reason not in pending_restart_reasons:
        pending_restart_reasons.append(reason)
    return pending_restart_status()


def pending_restart_status():
    return {
        'required': bool(pending_restart_reasons),
        'reason_count': len(pending_restart_reasons),
        'reasons': list(pending_restart_reasons),
    }


def _configured_portal_login_url(settings=None):
    settings = settings or credential_store.public_settings()
    transport = settings.get('portal_transport', 'auto')
    https = transport != 'http'
    port = settings.get('portal_port')
    if port is None:
        port = 8443 if https else 8080
    hostname = runtime_credentials.get('certificate', {}).get('hostname', '')
    return (
        ('https' if https else 'http') + '://' + hostname + ':' +
        str(port) + '/login'
        if hostname else '/login'
    )


def request_pending_restart():
    logOutput('Local', 'Device control', {'log': 'Authenticated restart requested', 'force': True, 'audit': True}, 'INFO')
    schedule_hardware_reset('portal_requested_reboot')
    return {
        'message': 'Committed changes are being activated. The device is restarting.',
        'login_url': _configured_portal_login_url(),
    }


def request_device_shutdown():
    logOutput(
        'Local', 'Device control', {'log': 'Authenticated shutdown requested',
        'force': True, 'audit': True}, 'INFO'
    )
    schedule_hardware_shutdown('portal_requested_shutdown')
    return {
        'message': 'The device is shutting down into deep sleep. Power-cycle '
        'or externally reset it to start again.',
    }


def start_portal_task(name, coroutine, message):
    portal_tasks[name] = {
        'phase': 'running',
        'message': str(message),
    }

    async def runner():
        try:
            result = await coroutine
        except Exception as exc:
            portal_tasks[name] = {
                'phase': 'failed',
                'message': str(exc) or exc.__class__.__name__,
            }
            logOutput(
                'Local', 'Task',
                {'log': name + ' stopped - ' + str(exc)}, 'ERROR'
            )
        else:
            portal_tasks[name] = {
                'phase': 'complete',
                'percent': 100,
                'message': str(result or 'Complete'),
            }

    asyncio.create_task(runner())
    return {
        'task_id': name,
        'message': str(message),
    }


def portal_task_status(name):
    return portal_tasks.get(
        str(name),
        {'phase': 'failed', 'message': 'Task was not found'}
    )


def portal_task_progress(name):
    labels = {
        'receiving': 'Downloading release',
        'writing': 'Writing core firmware',
        'verification': 'Verifying release',
    }

    async def report(phase, completed=0, total=0):
        total = int(total or 0)
        completed = int(completed or 0)
        portal_tasks[name] = {
            'phase': 'running',
            'message': labels.get(str(phase), str(phase).replace('_', ' ')),
            'percent': max(0, min(100, int(completed * 100 / total))) if total else 0,
        }

    return report


set_log_output(logOutput)

logOutput(
    'Local',
    'Device',
    {'log': 'Imported signed application settings: ' + device_settings.APP_SETTINGS_FILE},
    'INFO'
)


def wifi_ip_address():
    if network is None:
        return web_portal_host

    try:
        wlan = network.WLAN(network.STA_IF)
        ip_address = wlan.ifconfig()[0]
        if ip_address and ip_address != '0.0.0.0':
            return ip_address
    except Exception:
        pass

    return web_portal_host


def web_portal_url():
    if not web_portal_enabled or not web_portal_password_verifier:
        return None

    scheme = 'https' if web_portal_https else 'http'
    host = certificate_config.get('hostname', '') or wifi_ip_address()
    return scheme + '://' + host + ':' + str(web_portal_port) + '/'


def uptime_seconds():
    return max(0, int(ticks_diff(ticks_ms(), boot_ms) / 1000))


def mqtt_connection_status():
    if not mqtt_configured:
        return 'not configured'
    try:
        isconnected = getattr(client, 'isconnected', None)
        if callable(isconnected):
            return 'up' if isconnected() else 'down'
        if isconnected is not None:
            return 'up' if isconnected else 'down'
        if getattr(client, 'up', None):
            return 'up' if client.up.is_set() else 'down'
    except Exception:
        pass
    return 'unknown'


def local_display_status():
    alerts = []
    if log_buffer:
        for line in reversed(log_buffer[-10:]):
            if 'ERROR' in line:
                alerts.append(line[-64:])
                if len(alerts) >= 3:
                    break

    status = {
        'device_name': ha_devicename,
        'wifi_ip': wifi_ip_address(),
        'mqtt': mqtt_connection_status(),
        'api': 'online' if device_api_server is not None else (
            'enabled' if device_api_enabled else 'disabled'
        ),
        'config': moduleSettingsFile,
        'loglevel': get_loglevel(),
        'web_portal': web_portal_enabled,
        'uptime_s': uptime_seconds(),
        'discovery_count': last_discovery_count,
        'alerts': alerts
    }
    if gc and hasattr(gc, 'mem_free'):
        status['heap_free_bytes'] = gc.mem_free()
        runtime_health.observe_heap(status['heap_free_bytes'])
    if gc and hasattr(gc, 'mem_alloc'):
        status['heap_allocated_bytes'] = gc.mem_alloc()
    return status


def local_display_snapshots():
    snapshots = []

    for device_char in outputDevices:
        if device_char.get('uuid') == '0000' or 'driver' not in device_char:
            continue

        device = next((d for d in deviceObjects if d.get('uuid') == device_char.get('uuid')), None)
        if not device:
            continue

        try:
            payload = device_char['driver'].get_state_payload()
            if hasattr(device_char['driver'], 'diagnostics_payload'):
                diagnostics = device_char['driver'].diagnostics_payload()
                if not diagnostics.get('last_ok', True) and diagnostics.get('last_error'):
                    payload['error'] = diagnostics.get('last_error')
        except Exception as exc:
            payload = {'error': str(exc)}

        snapshots.append({
            'name': device.get('name', device_char.get('uuid')),
            'payload': payload
        })

    return snapshots


def request_homeassistant_discovery():
    try:
        start_task('ha_discovery_manual', homeassistant_discovery())
        logOutput('Local', 'Display', {'log': 'Requested Home Assistant discovery'}, 'INFO')
    except Exception as exc:
        logOutput('Local', 'Display', {'log': 'Discovery request failed - ' + str(exc)}, 'ERROR')


def toggle_display_loglevel():
    next_level = 'DEBUG' if get_loglevel() != 'DEBUG' else 'INFO'
    set_loglevel(next_level)
    logOutput('Local', 'Display', {'log': 'Log level set to ' + next_level}, 'INFO')


def start_local_display():
    global local_display_service

    if not local_display_config or not local_display_config.get('enabled'):
        return

    actions = {
        'refresh_discovery': request_homeassistant_discovery,
        'toggle_loglevel': toggle_display_loglevel
    }

    try:
        local_display_service = LocalDisplayService(
            local_display_config,
            local_display_status,
            local_display_snapshots,
            actions,
            logOutput
        )
        if local_display_service.start():
            logOutput('Local', 'Display', {'log': 'Started local OLED display'}, 'INFO')
    except Exception as exc:
        local_display_service = None
        logOutput('Local', 'Display', {'log': 'Failed to start - ' + str(exc)}, 'ERROR')


def portal_status():
    status = local_display_status()
    update = app_update.update_status()
    status['running_version'] = app_update.running_version(
        device_settings.ha_device_info.get('sw', '')
    )
    status['base_version'] = hardware_platform.runtime_version()
    status['update_status'] = update.get('status', 'idle')
    status['update_version'] = update.get('version', '')
    status['update_options'] = update.get('optional_groups', [])
    firmware = firmware_update.update_status()
    firmware_capability = hardware_platform.firmware_ota_capability()
    status['platform'] = hardware_platform.platform_id()
    status['runtime_version'] = hardware_platform.runtime_version()
    status['firmware_update_supported'] = bool(
        web_portal_firmware_updates_enabled and firmware_capability.get('supported')
    )
    status['firmware_update_availability'] = (
        firmware_capability.get('reason', '')
        if web_portal_firmware_updates_enabled else
        'disabled by application policy'
    )
    status['firmware_update_status'] = firmware.get('status', 'idle')
    status['firmware_update_version'] = firmware.get('version', '')
    universal = universal_update.update_status()
    status['universal_update_status'] = universal.get('status', 'idle')
    status['universal_update_version'] = universal.get('version', '')
    status['firmware_running_version'] = firmware_update.running_version(
        hardware_platform.runtime_version()
    )
    slots = app_update.slot_status()
    storage = update_support.storage_status()
    status['active_slot'] = slots.get('active', '') or 'unavailable'
    previous = app_update.previous_slot()
    status['previous_slot'] = previous
    status['previous_slot_version'] = slots.get('versions', {}).get(previous, '')
    status['recovery_api'] = update_security.installed_recovery_api()
    status['signed_updates'] = update_security.signing_status()
    status['storage_free_bytes'] = storage.get('free_bytes', 0)
    status['storage_total_bytes'] = storage.get('total_bytes', 0)
    status['update_history'] = update_support.update_history()
    status['release_channel'] = release_channel
    status['release_available_version'] = release_available.get('version', '')
    status['release_available_type'] = release_available.get('type', '')
    status['release_available_sequence'] = release_available.get('release_sequence', 0)
    status['release_available_notes'] = release_available.get('notes', '')
    status['release_available_published_at'] = release_available.get('published_at', '')
    status['release_checks_enabled'] = bool(release_manifest_url)
    status['release_check_status'] = release_check_status
    status['release_last_checked'] = release_last_checked
    status['release_automatic_check_status'] = release_automatic_check_status
    status['release_automatic_last_checked'] = release_automatic_last_checked
    status['health_history'] = runtime_health.snapshot()
    status['timezone_name'] = timezone_name
    status['timezone_offset_minutes'] = timezone_rules.offset_minutes(timezone_name)
    status['api_enabled'] = device_api_enabled
    status['api_port'] = device_api_port
    status['mqtt_publish_queue'] = mqtt_publish_queue.stats()
    status['module_command_broker'] = module_broker.stats()
    status['remote_syslog'] = remote_syslog.status()
    status['paired_update'] = update_orchestrator.status()
    return status


def module_summaries():
    return build_module_summaries(outputDevices, deviceObjects, failedModules)


def configuration_backup():
    try:
        with open(moduleSettingsFile, 'r') as stream:
            modules = json.load(stream)
    except Exception:
        modules = {'devices': []}
    return configuration_manager.export_configuration(
        credential_store.public_settings(), modules, {
            'device_id': hardware_deviceid,
            'application_version': app_update.running_version(
                device_settings.ha_device_info.get('sw', '')
            ),
            'firmware_version': firmware_update.running_version(
                hardware_platform.runtime_version()
            ),
        }
    )


def _complete_backup_files():
    paths = {
        'portal_certificate': web_portal_cert_path,
        'portal_private_key': web_portal_key_path,
        'mqtt_ca': mqtt_ca_cert_path,
        'release_ca': release_ca_cert_path,
        'syslog_ca': device_settings.syslog_ca_path,
        'acme_account_key': certificate_manager.ACCOUNT_KEY_PATH,
        'acme_state': certificate_manager.STATE_PATH,
        'api_client_registry': device_settings.api_client_registry_path,
        'fleet_verification_key': fleet_management.FLEET_VERIFICATION_KEY_PATH,
        'fleet_state': fleet_management.DEFAULT_STATE_PATH,
    }
    for index, path in enumerate(api_client_ca_store.paths()):
        paths['api_client_ca_' + str(index)] = path
    result = {}
    for name, path in paths.items():
        try:
            with open(path, 'rb') as stream:
                payload = stream.read()
            if payload:
                result[name] = payload
        except OSError:
            pass
    return result


def secure_configuration_backup(password):
    try:
        with open(moduleSettingsFile, 'r') as stream:
            modules = json.load(stream)
    except Exception:
        modules = {'devices': []}
    return configuration_manager.export_secure_configuration(
        credential_store.load(require_provisioned=True), modules,
        _complete_backup_files(), password, {
            'device_id': hardware_deviceid,
            'application_version': app_update.running_version(
                device_settings.ha_device_info.get('sw', '')
            ),
            'firmware_version': firmware_update.running_version(
                hardware_platform.runtime_version()
            ),
        }
    )


def _secure_restore_targets(files):
    fixed = {
        'portal_certificate': web_portal_cert_path,
        'portal_private_key': web_portal_key_path,
        'mqtt_ca': mqtt_ca_cert_path,
        'release_ca': release_ca_cert_path,
        'syslog_ca': device_settings.syslog_ca_path,
        'acme_account_key': certificate_manager.ACCOUNT_KEY_PATH,
        'acme_state': certificate_manager.STATE_PATH,
        'api_client_registry': device_settings.api_client_registry_path,
        'fleet_verification_key': fleet_management.FLEET_VERIFICATION_KEY_PATH,
        'fleet_state': fleet_management.DEFAULT_STATE_PATH,
    }
    targets = {}
    for name, payload in files.items():
        if (
            name in ('portal_certificate', 'mqtt_ca', 'release_ca', 'syslog_ca') or
            name.startswith('api_client_ca_')
        ):
            certificate_manager.decode_certificate(payload)
        if name in ('acme_state', 'api_client_registry', 'fleet_state'):
            try:
                structured = json.loads(payload.decode())
            except Exception:
                raise ValueError('encrypted backup contains invalid ' + name)
            if not isinstance(structured, dict):
                raise ValueError('encrypted backup contains invalid ' + name)
        if name == 'fleet_verification_key' and len(payload.strip()) not in (64, 128):
            raise ValueError('encrypted backup contains an invalid fleet verification key')
        if name in fixed:
            targets[fixed[name]] = payload
        elif name.startswith('api_client_ca_'):
            fingerprint = api_security.certificate_fingerprint(payload)
            targets[
                device_settings.api_client_ca_directory + '/' +
                fingerprint[:24] + '.der'
            ] = payload
        else:
            raise ValueError('encrypted backup contains an unknown protected file')
    return targets


def preview_secure_configuration_import(request):
    global pending_secure_configuration_import
    if not isinstance(request, dict):
        raise ValueError('encrypted backup request is invalid')
    content = configuration_manager.parse_secure_import(
        request.get('backup'), request.get('password', '')
    )
    sections = configuration_manager.validate_restore_sections(
        request.get('sections')
    )
    credentials = None
    if 'credentials' in sections:
        credentials = credential_store.validate(
            content['credentials'], require_provisioned=True
        )
    modules = content['module_settings'] if 'module_settings' in sections else None
    if modules is not None:
        errors = validate_device_config(
            modules, device_types_for_devices(modules.get('devices', ()))
        )
        if errors:
            raise ValueError('module configuration rejected: ' + '; '.join(errors[:20]))
    targets = (
        _secure_restore_targets(content['files'])
        if 'certificates_and_trust' in sections else {}
    )
    portal_payloads = (
        targets.get(web_portal_cert_path), targets.get(web_portal_key_path)
    )
    if any(portal_payloads) and not all(portal_payloads):
        raise ValueError('encrypted backup must contain both portal identity files')
    try:
        with open(moduleSettingsFile, 'r') as stream:
            current_modules = json.load(stream)
    except Exception:
        current_modules = {'devices': []}
    preview = configuration_manager.secure_restore_preview(
        credential_store.load(require_provisioned=True), current_modules,
        _complete_backup_files(), content, hardware_deviceid, sections
    )
    token = hexlify(os.urandom(16)).decode()
    pending_secure_configuration_import = {
        'token': token,
        'created_ms': ticks_ms(),
        'credentials': credentials,
        'modules': modules,
        'files': targets,
        'sections': sections,
    }
    return {
        'token': token,
        'groups': sections,
        'file_count': len(targets),
        'device_id': content.get('metadata', {}).get('device_id', ''),
        'changes': preview['changes'],
        'change_count': preview['change_count'],
    }


def apply_secure_configuration_import(token):
    global pending_secure_configuration_import
    pending = pending_secure_configuration_import
    if (
        not pending or str(token) != pending.get('token') or
        ticks_diff(ticks_ms(), pending.get('created_ms', 0)) > 600000
    ):
        raise ValueError('encrypted backup preview has expired')
    module_temporary = moduleSettingsFile + '.secure-restore'
    if pending['modules'] is not None:
        with open(module_temporary, 'w') as stream:
            json.dump(pending['modules'], stream)
    staged_pairs = []
    api_client_ca_store._mkdir()
    for target, payload in pending['files'].items():
        staged = target + '.secure-restore'
        with open(staged, 'wb') as stream:
            stream.write(payload)
        staged_pairs.append((staged, target))
    staged_portal_certificate = next(
        (source for source, target in staged_pairs if target == web_portal_cert_path), None
    )
    staged_portal_key = next(
        (source for source, target in staged_pairs if target == web_portal_key_path), None
    )
    if staged_portal_certificate and staged_portal_key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(staged_portal_certificate, staged_portal_key)
    if pending['modules'] is not None:
        update_support.commit_file_with_backup(module_temporary, moduleSettingsFile)
    if staged_pairs:
        certificate_manager.commit_certificate_files(tuple(staged_pairs))
    if pending['credentials'] is not None:
        credential_store.save(pending['credentials'])
    pending_secure_configuration_import = None
    runtime_health.record_event(
        'secure_configuration_restore',
        'Selected encrypted backup sections restored: ' +
        ', '.join(pending.get('sections', ())), force=True, component='backup'
    )
    mark_restart_required('Encrypted configuration restored')
    return 'Complete encrypted backup restored. Restart the device to activate it.'


def preview_configuration_import(payload):
    global pending_configuration_import
    try:
        with open(moduleSettingsFile, 'r') as stream:
            current_modules = json.load(stream)
    except Exception:
        current_modules = {'devices': []}
    plan = configuration_manager.prepare_import(
        payload,
        credential_store.public_settings(),
        current_modules,
        credential_store.preview_operational_settings,
        lambda candidate: validate_device_config(
            candidate, device_types_for_devices(candidate.get('devices', ()))
        )
    )
    token = hexlify(os.urandom(16)).decode()
    pending_configuration_import = {
        'token': token,
        'plan': plan,
        'created_ms': ticks_ms(),
    }
    return {
        'token': token,
        'change_count': plan['change_count'],
        'changes': plan['changes'],
    }


def apply_configuration_import(token):
    global pending_configuration_import
    pending = pending_configuration_import
    if (
        not pending or str(token) != pending.get('token') or
        ticks_diff(ticks_ms(), pending.get('created_ms', 0)) > 600000
    ):
        raise ValueError('configuration import preview has expired')
    plan = pending['plan']
    if not plan.get('changes'):
        raise ValueError('configuration import contains no changes')
    previous = credential_store.load(require_provisioned=True)
    candidate = credential_store.preview_operational_settings(plan['settings'])
    temporary = moduleSettingsFile + '.import'
    modules = plan.get('module_settings')
    if modules is not None:
        with open(temporary, 'w') as stream:
            json.dump(modules, stream)
    try:
        credential_store.begin_network_trial(previous, candidate)
        if modules is not None:
            update_support.commit_file_with_backup(temporary, moduleSettingsFile)
    except Exception:
        credential_store.save(previous)
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise
    pending_configuration_import = None
    runtime_health.record_event(
        'configuration_import', str(plan['change_count']) + ' changes', force=True
    )
    mark_restart_required('Configuration restored')
    return 'Configuration imported and validated. Restart the device to activate it.'


def portal_settings():
    settings = credential_store.public_settings()
    settings['api_clients'] = api_client_registry.list_clients()
    settings['api_client_ca_installed'] = bool(api_client_ca_store.paths())
    return settings


def installed_certificate_details():
    return {
        'portal': certificate_manager.certificate_lifecycle(web_portal_cert_path),
        'trusted_ca': certificate_manager.certificate_lifecycle(mqtt_ca_cert_path),
        'mqtt_ca': certificate_manager.certificate_lifecycle(mqtt_ca_cert_path),
        'release_ca': certificate_manager.certificate_lifecycle(release_ca_cert_path),
        'api_client_ca': {'installed': False},
        'api_client_cas': api_client_ca_store.list(),
        'api_clients': api_client_registry.list_clients(),
        'syslog_ca': certificate_manager.certificate_lifecycle(
            device_settings.syslog_ca_path
        ),
        'acme_settings': dict(certificate_config),
    }


async def certificate_alert_monitor():
    previous = {}
    while True:
        for name, path in (
            ('portal', web_portal_cert_path),
            ('mqtt_ca', mqtt_ca_cert_path),
            ('release_ca', release_ca_cert_path),
            ('syslog_ca', device_settings.syslog_ca_path),
        ):
            details = certificate_manager.certificate_lifecycle(path)
            level = details.get('expiry_level')
            if level in ('warning', 'critical', 'expired') and previous.get(name) != level:
                days = details.get('days_remaining')
                message = name + ' certificate '
                message += (
                    'expired' if level == 'expired' else
                    'expires in ' + str(days) + ' days'
                )
                logOutput('Local', 'Certificate lifecycle', {'log': message}, 'ERROR')
                runtime_health.record_event(
                    'certificate_' + level, message,
                    {'certificate': name, 'days_remaining': days}, force=True
                )
            previous[name] = level
        for ca in api_client_ca_store.list():
            fingerprint = str(ca.get('fingerprint', ''))
            key = 'api_ca_' + fingerprint
            level = ca.get('expiry_level')
            if level in ('warning', 'critical', 'expired') and previous.get(key) != level:
                days = ca.get('days_remaining')
                message = 'API client CA ' + fingerprint[:12] + ' '
                message += (
                    'expired' if level == 'expired' else
                    'expires in ' + str(days) + ' days'
                )
                logOutput('Local', 'Certificate lifecycle', {'log': message}, 'ERROR')
                runtime_health.record_event(
                    'certificate_' + level, message,
                    {'certificate': key, 'days_remaining': days}, force=True
                )
            previous[key] = level
        for client in api_client_registry.list_clients():
            fingerprint = str(client.get('fingerprint', ''))
            key = 'api_client_' + fingerprint
            level = client.get('expiry_level')
            if level in ('warning', 'critical', 'expired') and previous.get(key) != level:
                days = client.get('days_remaining')
                label = str(client.get('label', fingerprint[:12]))
                message = 'API client ' + label + ' certificate '
                message += (
                    'expired' if level == 'expired' else
                    'expires in ' + str(days) + ' days'
                )
                logOutput('Local', 'Certificate lifecycle', {'log': message}, 'ERROR')
                runtime_health.record_event(
                    'certificate_' + level, message,
                    {'certificate': key, 'days_remaining': days}, force=True
                )
            previous[key] = level
        await asyncio.sleep(21600)


def update_portal_settings(params):
    current_settings = credential_store.public_settings()
    ntp_servers = [
        server.strip() for server in str(params.get('ntp_servers', '')).split(',')
        if server.strip()
    ]
    if 'portal_session_timeout_minutes' in params:
        portal_timeout_s = int(params.get('portal_session_timeout_minutes', 60)) * 60
    else:
        portal_timeout_s = int(params.get('portal_session_timeout_s', 3600))
    values = {
        'device_name': str(params.get('device_name', '')).strip(),
        'wifi_ssid': str(params.get('wifi_ssid', '')),
        'wifi_dhcp': str(params.get('wifi_dhcp', '')).lower() in (
            '1', 'true', 'on'
        ),
        'wifi_ip_address': str(params.get('wifi_ip_address', '')).strip(),
        'wifi_subnet_mask': str(params.get('wifi_subnet_mask', '')).strip(),
        'wifi_gateway': str(params.get('wifi_gateway', '')).strip(),
        'wifi_dns_server': str(params.get('wifi_dns_server', '')).strip(),
        'mqtt_server': str(params.get('mqtt_server', '')).strip(),
        'mqtt_port': params.get('mqtt_port', 8883),
        'mqtt_username': str(params.get('mqtt_username', '')),
        'portal_username': str(params.get('portal_username', '')).strip(),
        'portal_transport': str(params.get('portal_transport', 'auto')).strip(),
        'portal_port': str(params.get('portal_port', '')).strip(),
        'portal_session_timeout_s': portal_timeout_s,
        'ntp_servers': ntp_servers,
        'timezone_name': str(params.get('timezone_name', 'UTC')),
        'timezone_offset_minutes': timezone_rules.offset_minutes(
            str(params.get('timezone_name', 'UTC'))
        ),
        'ha_discovery': str(params.get('ha_discovery', '')).lower() in (
            '1', 'true', 'on'
        ),
        'log_buffer_lines': int(params.get('log_buffer_lines', 200)),
        'syslog_enabled': str(params.get('syslog_enabled', '')).lower() in (
            '1', 'true', 'on'
        ),
        'syslog_audit_enabled': str(
            params.get('syslog_audit_enabled', '')
        ).lower() in ('1', 'true', 'on'),
        'syslog_host': str(params.get('syslog_host', '')).strip(),
        'syslog_port': int(params.get('syslog_port', 514)),
        'syslog_transport': str(params.get('syslog_transport', 'udp')).strip(),
    }
    if 'api_enabled' in params or 'api_port' in params:
        values['api_enabled'] = str(params.get('api_enabled', '')).lower() in (
            '1', 'true', 'on'
        )
        values['api_port'] = int(params.get('api_port', device_settings.device_api_port))
    wifi_password = str(params.get('wifi_password', ''))
    clear_wifi = str(params.get('clear_wifi_password', '')).lower() in ('1', 'true', 'on')
    if wifi_password and clear_wifi:
        raise ValueError('choose either a new Wi-Fi password or clear the stored password')
    if wifi_password or clear_wifi:
        values['wifi_password'] = wifi_password

    mqtt_password = str(params.get('mqtt_password', ''))
    clear_mqtt = str(params.get('clear_mqtt_password', '')).lower() in ('1', 'true', 'on')
    if mqtt_password and clear_mqtt:
        raise ValueError('choose either a new MQTT password or clear the stored password')
    if mqtt_password or clear_mqtt:
        values['mqtt_password'] = mqtt_password

    candidate_network = dict(values)
    candidate_network['portal_port'] = (
        int(values['portal_port']) if values['portal_port'] else None
    )
    network_keys = (
        'device_name', 'wifi_ssid', 'wifi_dhcp', 'wifi_ip_address',
        'wifi_subnet_mask', 'wifi_gateway', 'wifi_dns_server',
        'portal_transport', 'portal_port'
    )
    network_changed = bool(wifi_password or clear_wifi) or any(
        candidate_network.get(key) != current_settings.get(key) for key in network_keys
    )
    updated = credential_store.update_operational_settings(
        values, network_trial=network_changed
    )

    mark_restart_required('System settings changed')
    login_url = _configured_portal_login_url(updated)
    message = 'Settings saved securely. Restart the device when all changes are complete.'
    if updated.get('network_trial_pending'):
        message = (
            'Network settings saved. After restarting, sign in to the portal within ' +
            str(network_trial_timeout_s) +
            ' seconds or the previous network settings will be restored.'
        )
    return {
        'message': message,
        'login_url': login_url,
    }


def update_release_preferences(params):
    global release_channel, release_auto_download, release_auto_activate
    global release_check_schedule, release_check_time, release_check_weekday
    current = credential_store.public_settings()
    schedule = str(params.get('release_check_schedule', 'disabled'))
    check_time = str(params.get(
        'release_check_time', current.get('release_check_time', '03:00')
    ))
    try:
        weekday = int(params.get(
            'release_check_weekday', current.get('release_check_weekday', 0)
        ))
        hour, minute = [int(part) for part in check_time.split(':')]
    except (TypeError, ValueError):
        raise ValueError('automatic update check time must use HH:MM')
    if schedule not in ('disabled', 'daily', 'weekly'):
        raise ValueError('automatic update check schedule is invalid')
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError('automatic update check time is invalid')
    if not 0 <= weekday <= 6:
        raise ValueError('automatic update check weekday is invalid')
    check_time = '{:02}:{:02}'.format(hour, minute)
    values = {
        'release_channel': str(params.get('release_channel', 'stable')),
        'release_auto_download': str(
            params.get('release_auto_download', '')
        ).lower() in ('1', 'true', 'on'),
        'release_auto_activate': str(
            params.get('release_auto_activate', '')
        ).lower() in ('1', 'true', 'on'),
        'release_check_schedule': schedule,
        'release_check_time': check_time,
        'release_check_weekday': weekday,
    }
    credential_store.update_operational_settings(values)
    release_channel = values['release_channel']
    release_auto_download = values['release_auto_download']
    release_auto_activate = values['release_auto_activate']
    release_check_schedule = values['release_check_schedule']
    release_check_time = values['release_check_time']
    release_check_weekday = values['release_check_weekday']
    return 'Update preferences saved'


def module_settings_json():
    try:
        value = update_support.load_json_with_backup(moduleSettingsFile)
    except Exception:
        value = {'devices': []}
    return json.dumps(value)


def update_module_settings(payload):
    if isinstance(payload, str):
        candidate = json.loads(payload)
    else:
        candidate = payload
    if not isinstance(candidate, dict):
        raise ValueError('module settings must be a JSON object')
    devices = candidate.get('devices')
    types = device_types_for_devices(devices)
    errors = validate_device_config(candidate, types)
    if errors:
        raise ValueError('; '.join(errors))

    temporary = moduleSettingsFile + '.tmp'
    with open(temporary, 'w') as stream:
        stream.write(json.dumps(candidate))
    update_support.commit_file_with_backup(temporary, moduleSettingsFile)

    mark_restart_required('Module configuration changed')
    return 'Module settings saved and verified. Restart the device to activate them.'


async def upload_certificate_file(kind, reader, length):
    paths = {
        'trust-ca': mqtt_ca_cert_path,
        'mqtt-ca': getattr(__import__('device_config'), 'MQTT_CA_PATH', mqtt_ca_cert_path),
        'release-ca': getattr(__import__('device_config'), 'RELEASE_CA_PATH', release_ca_cert_path),
        'api-client-ca': 'certs/api-client-ca-stage.der',
        'api-client-cert': 'certs/api-client-enrol.der',
        'fleet-client-cert': 'certs/fleet-client-enrol.der',
        'syslog-ca': device_settings.syslog_ca_path,
        'portal-cert': web_portal_cert_path,
        'portal-key': web_portal_key_path,
    }
    path = paths.get(kind)
    if not path:
        raise ValueError('unknown certificate type')
    payload = bytearray()
    while len(payload) < length:
        chunk = await reader.read(min(1024, length - len(payload)))
        if not chunk:
            raise ValueError('certificate upload ended early')
        payload.extend(chunk)
    if b'-----BEGIN' in payload:
        raise ValueError('certificate files must use DER, not PEM')
    if kind in ('api-client-ca', 'api-client-cert', 'fleet-client-cert'):
        certificate_manager.decode_certificate(bytes(payload))
        fingerprint = api_security.certificate_fingerprint(payload)[:24]
        path = (
            'certs/.api-ca-stage-' if kind == 'api-client-ca' else
            ('certs/.fleet-client-stage-' if kind == 'fleet-client-cert' else
             'certs/.api-client-stage-')
        ) + fingerprint + '.der'
    temporary = path + '.manual'
    with open(temporary, 'wb') as stream:
        stream.write(payload)


async def _close_listener(server):
    if server is None:
        return
    server.close()
    if hasattr(server, 'wait_closed'):
        await server.wait_closed()


async def reload_portal_listener(delay_s=1):
    """Load a replaced portal identity without rebooting the device."""
    global web_portal_server
    await asyncio.sleep(delay_s)
    await _close_listener(web_portal_server)
    web_portal_server = None
    return await start_admin_portal()


async def reload_device_api_listener(delay_s=1):
    """Reload API client trust without interrupting module/MQTT runtime."""
    global device_api_server
    await asyncio.sleep(delay_s)
    await _close_listener(device_api_server)
    device_api_server = None
    return await start_module_api()


def schedule_portal_certificate_reload():
    start_task('portal_certificate_reload', reload_portal_listener())


def validate_uploaded_certificates():
    staged_ca = mqtt_ca_cert_path + '.manual'
    staged_cert = web_portal_cert_path + '.manual'
    staged_key = web_portal_key_path + '.manual'
    pairs = []

    def exists(path):
        try:
            return os.stat(path)[6] > 0
        except OSError:
            return False

    portal_staged = [exists(path) for path in (staged_cert, staged_key)]
    if any(portal_staged):
        if not all(portal_staged):
            raise ValueError('portal certificate and portal key must be uploaded together')
        server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server.load_cert_chain(staged_cert, staged_key)
        pairs.extend((
            (staged_cert, web_portal_cert_path),
            (staged_key, web_portal_key_path),
        ))

    mqtt_target = getattr(__import__('device_config'), 'MQTT_CA_PATH', mqtt_ca_cert_path)
    ca_stages = (
        (mqtt_target + '.manual' if exists(mqtt_target + '.manual') else staged_ca, mqtt_target),
        (getattr(__import__('device_config'), 'RELEASE_CA_PATH', release_ca_cert_path) + '.manual',
         getattr(__import__('device_config'), 'RELEASE_CA_PATH', release_ca_cert_path)),
        (device_settings.syslog_ca_path + '.manual', device_settings.syslog_ca_path),
    )
    outbound_trust_changed = False
    for staged, target in ca_stages:
        if not exists(staged):
            continue
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        try:
            context.load_verify_locations(cafile=staged)
        except TypeError:
            with open(staged, 'rb') as stream:
                context.load_verify_locations(cadata=stream.read())
        pairs.append((staged, target))
        outbound_trust_changed = True

    try:
        staged_names = os.listdir('certs')
    except OSError:
        staged_names = []
    api_ca_stages = [
        'certs/' + name for name in staged_names
        if name.startswith('.api-ca-stage-') and name.endswith('.der.manual')
    ]
    client_stages = [
        'certs/' + name for name in staged_names
        if name.startswith('.api-client-stage-') and name.endswith('.der.manual')
    ]
    fleet_client_stages = [
        'certs/' + name for name in staged_names
        if name.startswith('.fleet-client-stage-') and name.endswith('.der.manual')
    ]
    api_ca_payloads = []
    client_payloads = []
    fleet_client_payloads = []
    for staged in api_ca_stages:
        with open(staged, 'rb') as stream:
            payload = stream.read()
        certificate_manager.decode_certificate(payload)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        try:
            context.load_verify_locations(cafile=staged)
        except TypeError:
            context.load_verify_locations(cadata=payload)
        api_ca_payloads.append((staged, payload))
    for staged in client_stages:
        with open(staged, 'rb') as stream:
            payload = stream.read()
        certificate_manager.decode_certificate(payload)
        client_payloads.append((staged, payload))
    for staged in fleet_client_stages:
        with open(staged, 'rb') as stream:
            payload = stream.read()
        certificate_manager.decode_certificate(payload)
        fleet_client_payloads.append((staged, payload))

    if not pairs and not api_ca_payloads and not client_payloads and not fleet_client_payloads:
        raise ValueError('no staged certificate files were found')
    if pairs:
        certificate_manager.commit_certificate_files(tuple(pairs))
    for staged, payload in api_ca_payloads:
        api_client_ca_store.add(payload)
        try:
            os.remove(staged)
        except OSError:
            pass
    for staged, payload in client_payloads:
        api_client_registry.enrol(payload, scopes=('read', 'write'))
        try:
            os.remove(staged)
        except OSError:
            pass
    for staged, payload in fleet_client_payloads:
        api_client_registry.enrol(payload, scopes=('fleet:read', 'fleet:write'))
        try:
            os.remove(staged)
        except OSError:
            pass
    if all(portal_staged):
        credential_store.update_certificate_settings('manual')

    if outbound_trust_changed:
        mark_restart_required('Outbound TLS trust changed')
        return {
            'message': 'Outbound TLS trust validated. Restart the device to reload active client connections.',
            'restart': True,
        }
    reloaded = []
    if all(portal_staged):
        start_task('portal_certificate_reload', reload_portal_listener())
        reloaded.append('portal HTTPS')
    if api_ca_payloads:
        start_task('api_trust_reload', reload_device_api_listener())
        reloaded.append('Device API trust')
    if reloaded:
        return {
            'message': 'Certificates validated. Reloading ' +
                       ' and '.join(reloaded) + ' without a device restart.',
            'restart': False,
        }
    return {
        'message': 'API client certificates enrolled and active without a device restart.',
        'restart': False,
    }


def device_api_info():
    return {
        'device_name': ha_devicename,
        'device_id': hardware_deviceid,
        'application_version': app_update.running_version(
            device_settings.ha_device_info.get('sw', '')
        ),
        'firmware_version': firmware_update.running_version(
            hardware_platform.runtime_version()
        ),
        'micropython_version': hardware_platform.runtime_version(),
        'uptime_s': uptime_seconds(),
        'board': hardware_platform.platform_id(),
        'drivers': module_runtime.inventory()['drivers'],
        'resources': driver_loader.resource_catalog(),
        'runtime': application_context.inventory(),
        'release_sequence': app_update.running_release_sequence(),
        'firmware_release_sequence': firmware_update.running_release_sequence(),
    }


def device_support_bundle():
    return support_bundle.build_support_bundle(
        device_api_info(), event_service.health, module_summaries(), {
            'product': component_versions.PRODUCT_VERSION,
            'application': app_update.running_version(''),
            'firmware': firmware_update.running_version(''),
            'micropython': hardware_platform.runtime_version(),
        }, fleet_service, get_log_buffer()
    )


async def start_module_api():
    global device_api_server
    if not device_api_enabled:
        return None
    if not ntp_synced and time.localtime()[0] < 2024:
        logOutput(
            'API', 'Start',
            {'log': 'Waiting for a valid clock before enabling mTLS'}, 'ERROR'
        )
        return None
    api = DeviceAPI(
        module_broker, runtime_health, api_client_registry,
        device_api_info, logOutput, fleet_service, device_support_bundle
    )
    settings = {
        'enabled': True,
        'host': device_settings.device_api_host,
        'port': device_api_port,
        'cert_path': web_portal_cert_path,
        'key_path': web_portal_key_path,
        'client_ca_paths': api_client_ca_store.paths(),
        'max_body_bytes': device_settings.device_api_max_body_bytes,
    }
    try:
        device_api_server = await start_device_api(settings, api)
    except Exception as exc:
        logOutput('API', 'Start', {'log': 'Failed - ' + str(exc)}, 'ERROR')
        return None
    logOutput(
        'API', 'Start',
        {'log': 'mTLS API listening on port ' + str(device_api_port)}, 'INFO'
    )
    return device_api_server


def system_info_payload():
    update = app_update.update_status()
    firmware = firmware_update.update_status()
    storage = update_support.storage_status()
    history = update_support.update_history()
    last_event = history[-1] if history else {}
    return {
        'firmware_version': device_settings.ha_device_info.get('sw', ''),
        'application_version': app_update.running_version(
            device_settings.ha_device_info.get('sw', '')
        ),
        'base_firmware_version': firmware_update.running_version(
            hardware_platform.runtime_version()
        ),
        'application_update_status': update.get('status', 'idle'),
        'firmware_update_status': firmware.get('status', 'idle'),
        'staged_application_version': update.get('version', ''),
        'staged_firmware_version': firmware.get('version', ''),
        'recovery_api': update_security.installed_recovery_api(),
        'signed_updates': update_security.signing_status(),
        'storage_free_bytes': storage.get('free_bytes', 0),
        'active_application_slot': app_update.active_slot() or 'unavailable',
        'update_available': release_available.get('version', ''),
        'last_update_event': last_event.get('event', ''),
        'last_rollback_reason': (
            last_event.get('detail', '')
            if 'rollback' in str(last_event.get('event', '')) else ''
        ),
        'recovery_mode': False,
        'module_settings_file': moduleSettingsFile,
        'loaded_modules': len([d for d in deviceObjects if d.get('uuid') != '0000']),
        'wifi_ip': wifi_ip_address(),
        'uptime_s': uptime_seconds(),
        'discovery_count': last_discovery_count
    }


def system_info_discovery():
    payloads = {}
    for key in system_info_payload():
        payloads[key] = {
            '~': ha_device_topic('sensor', deviceid, 'sys'),
            'stat_t': '~/state',
            'uniq_id': ha_unique_id(deviceid, 'sys', key),
            'name': ha_devicename + ' ' + key,
            'value_template': "{{ value_json[" + repr(key) + "] }}",
            'availability_topic': ha_availability_topic(deviceid),
            'payload_available': 'online',
            'payload_not_available': 'offline',
            'entity_category': 'diagnostic',
            'en': False,
            'dev': homeassistant_device_info(deviceid, ha_devicename, web_portal_url()),
            'o': homeassistant_origin_info()
        }
    return payloads


def maintenance_discovery():
    commands = {
        'reboot': 'Reboot device',
        'check_release': 'Check for update',
        'rollback_application': 'Rollback application',
    }
    payloads = {}
    command_topic = ha_set_topic('button', deviceid, 'maint')
    for command, name in commands.items():
        payloads[command] = {
            'cmd_t': command_topic,
            'pl_prs': command,
            'uniq_id': ha_unique_id(deviceid, 'maint', command),
            'name': name,
            'entity_category': 'config',
            'en': False,
            'availability_topic': ha_availability_topic(deviceid),
            'dev': homeassistant_device_info(deviceid, ha_devicename, web_portal_url()),
            'o': homeassistant_origin_info(),
        }
    return payloads


def module_health_payload(driver):
    if not hasattr(driver, 'diagnostics_payload'):
        return {}
    try:
        health = driver.diagnostics_payload()
    except Exception:
        return {}
    payload = {}
    for key in ('last_ok', 'last_error', 'last_read_ms', 'last_publish_age_s', 'consecutive_errors'):
        payload['module_' + key] = health.get(key)
    return payload


def portal_action(action, params):
    if action == 'discover':
        request_homeassistant_discovery()
        return 'Discovery requested'

    if action == 'calibrate':
        uuid = params.get('uuid')
        known_voltage = params.get('known_voltage')
        device_char = next((d for d in outputDevices if d.get('uuid') == uuid), None)
        if not device_char or 'driver' not in device_char:
            return 'Calibration failed: module not found'
        driver = device_char['driver']
        if not hasattr(driver, 'set_calibration'):
            return 'Calibration failed: module does not support calibration'
        previous_calibration = getattr(driver, 'calibration', None)
        result = driver.set_calibration({'known_voltage': known_voltage})
        if isinstance(result, dict) and result.get('ok'):
            try:
                candidate = update_support.load_json_with_backup(moduleSettingsFile)
                configured = next(
                    (item for item in candidate.get('devices', ())
                     if str(item.get('uuid')) == str(uuid)), None
                )
                if configured is None:
                    raise ValueError('module is missing from persistent configuration')
                configured.setdefault('ac_voltage', {})['calibration'] = result['calibration']
                errors = validate_device_config(
                    candidate,
                    device_types_for_devices(candidate.get('devices', ()))
                )
                if errors:
                    raise ValueError('; '.join(errors))
                temporary = moduleSettingsFile + '.calibration'
                with open(temporary, 'w') as stream:
                    json.dump(candidate, stream)
                update_support.commit_file_with_backup(temporary, moduleSettingsFile)
            except Exception as exc:
                if previous_calibration is not None:
                    driver.calibration = previous_calibration
                    driver.device.setdefault('ac_voltage', {})['calibration'] = previous_calibration
                return 'Calibration failed to persist: ' + str(exc)
            runtime_health.record_event(
                'module_calibration', 'Calibration updated for ' + str(uuid),
                {'module': str(uuid), 'calibration': result['calibration']}, force=True
            )
            return 'Calibration set to ' + str(result.get('calibration')) + ' for module ' + str(uuid)
        if isinstance(result, dict):
            return 'Calibration failed: ' + str(result.get('error', result))
        return 'Calibration failed'

    if action == 'reset-health-history':
        runtime_health.clear()
        return 'Health history reset'

    if action == 'update-acme-settings':
        enabled = str(params.get('acme_enabled', '')).lower() in (
            '1', 'true', 'on'
        )
        directory_url = str(
            params.get('directory_url', certificate_config.get('directory_url', ''))
        ).strip()
        hostname = str(
            params.get('hostname', certificate_config.get('hostname', ''))
        ).strip().lower().rstrip('.')
        credential_store.update_certificate_settings(
            'acme' if enabled else 'manual', directory_url, hostname
        )
        mark_restart_required('ACME settings changed')
        return (
            'ACME certificate management enabled. Restart the device to activate it.'
            if enabled else
            'ACME certificate management disabled. The installed certificate is retained; restart to activate the change.'
        )

    if action == 'ems-debug':
        uuid = params.get('uuid')
        enabled = str(params.get('enabled', '')).lower() in ('1', 'true', 'on')
        device_char = next((d for d in outputDevices if d.get('uuid') == uuid), None)
        if not device_char or 'driver' not in device_char:
            return 'EMS debug change failed: module not found'
        driver = device_char['driver']
        if not hasattr(driver, 'set_debug_frames'):
            return 'EMS debug change failed: module does not support frame debugging'
        current = driver.set_debug_frames(enabled)
        state = 'enabled' if current else 'disabled'
        return 'EMS debug frames ' + state + ' for module ' + str(uuid)

    if action == 'revoke-api-client':
        fingerprint = str(params.get('fingerprint', '')).strip().lower()
        if not api_client_registry.revoke(fingerprint):
            return 'API client was not found'
        return 'API client certificate revoked'

    if action == 'activate-update':
        state = app_update.update_status()
        if state.get('status') != 'ready':
            return 'Application update activation failed: no staged update'
        selections = {
            'module_settings': str(params.get('module_settings', '')).lower() in ('1', 'true', 'on'),
            'certificates': str(params.get('certificates', '')).lower() in ('1', 'true', 'on')
        }
        try:
            app_update.configure_pending_update(selections)
            update_orchestrator.mark_activating('application')
        except Exception as exc:
            return 'Application update activation failed: ' + str(exc)

        schedule_hardware_reset('application_update_reboot', 8000)
        return 'Application update staged; rebooting'

    if action == 'activate-firmware':
        if not web_portal_firmware_updates_enabled or not firmware_update.supported():
            return 'Base firmware activation failed: firmware OTA is unavailable'
        try:
            firmware_update.activate_pending()
            update_orchestrator.mark_activating('firmware')
        except Exception as exc:
            return 'Base firmware activation failed: ' + str(exc)

        schedule_hardware_reset('firmware_update_reboot', 8000)
        return 'Base firmware staged; rebooting into trial partition'

    if action == 'activate-universal':
        if not web_portal_firmware_updates_enabled or not firmware_update.supported():
            return 'Universal update activation failed: firmware OTA is unavailable'
        try:
            fleet_snapshot = fleet_service.snapshot()
            fleet_policy = fleet_snapshot.get('policy') or {}
            maintenance_allowed = (
                not fleet_policy or fleet_snapshot.get('within_maintenance_window')
            )
            universal_update.activate_pending(maintenance_allowed)
        except Exception as exc:
            return 'Universal update activation failed: ' + str(exc)
        schedule_hardware_reset('universal_update_reboot', 8000)
        return 'Universal core and application update staged; rebooting into trial versions'

    if action == 'rollback-application':
        try:
            result = app_update.rollback_to_previous()
        except Exception as exc:
            return 'Application rollback failed: ' + str(exc)

        schedule_hardware_reset('application_manual_rollback', 8000)
        return (
            'Application switched to slot ' + str(result.get('active', '')) +
            '; rebooting'
        )

    if action == 'check-release':
        if not release_manifest_url:
            return 'Release checks are not configured'
        return start_portal_task(
            'release_check_manual', check_release_once(),
            'Checking the signed release channel'
        )

    if action == 'download-release':
        if not release_manifest_url:
            return 'Release download failed: release checks are not configured'
        if not release_available:
            return 'Release download failed: check for updates first'
        return start_portal_task(
            'release_download_manual', download_release_once(
                portal_task_progress('release_download_manual')
            ),
            'Downloading and verifying the signed release'
        )

    if action == 'validate-configuration':
        try:
            candidate = json.loads(params.get('config_json', ''))
        except Exception as exc:
            return 'Invalid JSON: ' + str(exc)
        errors = validate_device_config(candidate, deviceTypes)
        if errors:
            displayed = errors[:20]
            suffix = ''
            if len(errors) > len(displayed):
                suffix = '\n- ... ' + str(len(errors) - len(displayed)) + ' more errors'
            return 'Configuration rejected:\n- ' + '\n- '.join(displayed) + suffix
        return 'Configuration is valid. No files were changed.'

    return 'Unknown action'


def fleet_activation_allowed():
    snapshot = fleet_service.snapshot()
    policy = snapshot.get('policy') or {}
    if not policy:
        return True
    updates = policy.get('updates') or {}
    return bool(
        updates.get('automatic_activation') and
        not snapshot.get('rollout_paused') and
        snapshot.get('within_maintenance_window')
    )


async def fleet_policy_monitor():
    """Execute only bounded commands carried by a verified fleet policy."""
    while True:
        for command in fleet_service.pending_commands():
            identifier = command.get('id', '')
            action = command.get('action', '')
            try:
                if action == 'check-update':
                    await check_release_once(False)
                elif action == 'download-update':
                    await download_release_once()
                elif action == 'activate-update':
                    if not fleet_service.within_maintenance_window():
                        raise RuntimeError('outside fleet maintenance window')
                    status = universal_update.update_status()
                    if status.get('status') == 'ready':
                        result = portal_action('activate-universal', {})
                    elif firmware_update.update_status().get('status') == 'ready':
                        result = portal_action('activate-firmware', {})
                    else:
                        result = portal_action('activate-update', {})
                    if 'failed' in str(result).lower():
                        raise RuntimeError(result)
                elif action == 'rollback':
                    result = portal_action('rollback-application', {})
                    if 'failed' in str(result).lower():
                        raise RuntimeError(result)
                else:
                    raise RuntimeError('unsupported fleet command')
            except Exception as exc:
                fleet_service.complete_command(identifier, 'failed', str(exc))
                runtime_health.record_event(
                    'fleet_command_failed', str(exc),
                    {'command': identifier, 'action': action}, force=True,
                    severity='error', component='fleet',
                    correlation_id=identifier
                )
            else:
                fleet_service.complete_command(identifier, 'complete', action)
                runtime_health.record_event(
                    'fleet_command_complete', action,
                    {'command': identifier}, force=True, component='fleet',
                    correlation_id=identifier
                )
        await asyncio.sleep(30)


async def portal_update_upload(reader, content_length, params):
    if not web_portal_updates_enabled:
        raise ValueError('application updates are disabled')
    state = await app_update.receive_bundle(
        reader,
        content_length,
        web_portal_allow_protected_updates,
        web_portal_update_max_bytes,
        progress_callback=params.get('_progress')
    )
    return (
        'Update ' + str(state.get('version', '')) +
        ' uploaded and verified; choose overwrite options before activation'
    )


async def portal_firmware_upload(reader, content_length, params):
    if not web_portal_firmware_updates_enabled:
        raise ValueError('base firmware updates are disabled by application policy')
    capability = hardware_platform.firmware_ota_capability()
    if not capability.get('supported'):
        raise ValueError(
            'base firmware updates are unavailable: ' +
            str(capability.get('reason', 'unknown OTA capability failure'))
        )
    state = await firmware_update.receive_bundle(
        reader,
        content_length,
        web_portal_firmware_update_max_bytes,
        progress_callback=params.get('_progress')
    )
    return (
        'Base firmware ' + str(state.get('version', '')) +
        ' verified in inactive partition; activate when ready'
    )


async def portal_universal_upload(reader, content_length, params):
    if not web_portal_updates_enabled or not web_portal_firmware_updates_enabled:
        raise ValueError('universal updates are disabled by application policy')
    capability = hardware_platform.firmware_ota_capability()
    if not capability.get('supported'):
        raise ValueError(
            'universal updates are unavailable: ' +
            str(capability.get('reason', 'unknown OTA capability failure'))
        )
    state = await universal_update.receive_bundle(
        reader, content_length,
        max(web_portal_update_max_bytes, web_portal_firmware_update_max_bytes),
        progress_callback=params.get('_progress')
    )
    return (
        'Universal update ' + str(state.get('version', '')) +
        ' verified; activate both components when ready'
    )


update_service = UpdateService(
    resumable_update_store,
    {
        'application': portal_update_upload if web_portal_updates_enabled else None,
        'firmware': (
            portal_firmware_upload if web_portal_firmware_updates_enabled else None
        ),
        'universal': portal_universal_upload,
    },
    status_getter=lambda: {
        'application': app_update.update_status(),
        'firmware': firmware_update.update_status(),
        'universal': universal_update.update_status(),
        'paired': update_orchestrator.status(),
    },
    maximum_chunk_bytes=resumable_upload.MAX_CHUNK_BYTES,
)
application_context.register('updates', update_service)


async def _check_release_once():
    global release_available
    releases = list(await release_update.fetch_releases(
        release_manifest_url, release_channel, release_ca_cert_path
    ))
    applicable = []
    for candidate in releases:
        if candidate.get('type') == 'application' and not release_update.application_release_applicable(
            candidate.get('components'),
            configured_driver_names(moduleSettings.get('devices', ())),
            component_versions.RUNTIME_VERSION,
            DRIVER_VERSIONS
        ):
            continue
        applicable.append(candidate)
    update_orchestrator.begin(
        applicable,
        app_update.running_release_sequence(),
        firmware_update.running_release_sequence(),
        app_update.running_version(device_settings.ha_device_info.get('sw', '')),
        firmware_update.running_version(hardware_platform.runtime_version())
    )
    release = update_orchestrator.next_release()
    if not release:
        release_available = {}
        return 'No newer compatible release'
    running = (
        app_update.running_version(device_settings.ha_device_info.get('sw', ''))
        if release.get('type') == 'application' else
        firmware_update.running_version(hardware_platform.runtime_version())
    )
    running_sequence = (
        app_update.running_release_sequence()
        if release.get('type') == 'application' else
        firmware_update.running_release_sequence()
    )
    release_sequence = int(release.get('release_sequence', 0))
    if (
        (running_sequence and release_sequence <= running_sequence) or
        (not running_sequence and str(release.get('version', '')) == str(running))
    ):
        release_available = {}
        return 'No newer release'
    release_available = release
    logOutput(
        'Local', 'Release update',
        {'log': 'Available ' + str(release.get('type')) + ' ' + str(release.get('version'))},
        'INFO'
    )
    if not release_auto_download:
        return 'Release available'
    return await download_release_once()


async def check_release_once(automatic=False):
    global release_check_status, release_last_checked
    global release_automatic_check_status, release_automatic_last_checked
    release_check_status = 'Checking'
    request_url = release_update.release_manifest_request_url(
        release_manifest_url, release_channel
    )
    logOutput(
        'Local', 'Release update',
        {'log': 'Checking ' + request_url, 'force': True}, 'INFO'
    )
    try:
        result = await _check_release_once()
    except Exception as exc:
        release_last_checked = wall_time_text()
        detail = str(exc).strip() or exc.__class__.__name__
        release_check_status = 'Check failed: ' + detail
        if automatic:
            release_automatic_check_status = release_check_status
            release_automatic_last_checked = release_last_checked
            runtime_health.observe('last_release_check', {
                'time': int(time.time()), 'status': release_check_status
            }, force=True)
        logOutput(
            'Local', 'Release update',
            {'log': release_check_status + ' — ' + request_url, 'force': True}, 'ERROR'
        )
        runtime_health.record_update_result('release', 'failed', detail=detail)
        raise
    release_last_checked = wall_time_text()
    release_check_status = str(result)
    if automatic:
        release_automatic_check_status = release_check_status
        release_automatic_last_checked = release_last_checked
        runtime_health.observe('last_release_check', {
            'time': int(time.time()), 'status': release_check_status
        }, force=True)
    logOutput(
        'Local', 'Release update',
        {'log': 'Check complete - ' + release_check_status + ' — ' + request_url}, 'INFO'
    )
    return result


async def download_release_once(progress_callback=None):
    global release_available
    release = release_available
    if not release:
        raise ValueError('no checked release is available')
    state = await release_update.stage_release(
        release,
        release_ca_cert_path,
        app_update.receive_bundle,
        firmware_update.receive_bundle,
        web_portal_allow_protected_updates,
        web_portal_update_max_bytes,
        web_portal_firmware_update_max_bytes,
        progress_callback
    )
    update_orchestrator.mark_staged(release)
    logOutput(
        'Local', 'Release update',
        {'log': 'Downloaded and staged ' + str(state.get('version', ''))},
        'INFO'
    )
    release_available = {}
    if release_auto_activate and fleet_activation_allowed():
        if release.get('type') == 'firmware':
            firmware_update.activate_pending()
        update_orchestrator.mark_activating(release.get('type'))
        await asyncio.sleep(1)
        hardware_platform.reset()
    return 'Release staged'


async def release_monitor():
    last_slot = ''
    while release_manifest_url:
        current = timezone_rules.localtime(name=timezone_name)
        slot = release_update.automatic_check_slot(
            release_check_schedule, release_check_time,
            release_check_weekday, current
        )
        if slot and slot != last_slot:
            last_slot = slot
            try:
                await check_release_once(True)
            except Exception:
                pass
        await asyncio.sleep(30)


async def start_admin_portal():
    global web_portal_server

    if not web_portal_enabled:
        return None

    if not web_portal_password_verifier:
        logOutput('Local', 'Web portal', {'log': 'Disabled: missing encrypted portal credentials'}, 'ERROR')
        return None

    scheme = 'https' if web_portal_https else 'http'
    configured_hostname = certificate_config.get('hostname', '') or wifi_ip_address()
    settings = {
        'https': web_portal_https,
        'host': web_portal_host,
        'port': web_portal_port,
        'username': web_portal_username,
        'password_verifier': web_portal_password_verifier,
        'password_change_required': web_portal_password_change_required,
        'password_setter': credential_store.update_portal_password,
        'authenticator': portal_auth.authenticate,
        'user_password_setter': lambda username, password: portal_auth.update_user(
            username, password=password
        ),
        'cert_path': web_portal_cert_path,
        'key_path': web_portal_key_path,
        'levels': tuple(loglevels),
        'log_refresh_ms': web_portal_log_refresh_s * 1000,
        'value_refresh_ms': web_portal_value_refresh_s * 1000,
        'session_timeout_s': web_portal_session_timeout_s,
        'login_url': (
            scheme + '://' + configured_hostname + ':' +
            str(web_portal_port) + '/login'
        ),
    }

    portal_url_host = wifi_ip_address()
    logOutput(
        'Local',
        'Web portal',
        {'log': (
            'Starting on ' + web_portal_host + ':' + str(web_portal_port) +
            ('' if web_portal_https else ' without TLS by explicit configuration')
        )},
        'INFO'
    )

    try:
        wifi_recovery.schedule_wifi_scan()
        dependencies = PortalDependencies(settings, {
            'logs.get': get_log_buffer,
            'audit.get': get_audit_log_buffer,
            'logs.level.get': get_loglevel,
            'logs.level.set': set_loglevel,
            'logs.limit.set': set_log_buffer_lines,
            'events.log': logOutput,
            'status.get': portal_status,
            'modules.list': module_summaries,
            'actions.apply': portal_action,
            'updates.preferences.apply': update_release_preferences,
            'updates.upload.begin': update_service.begin,
            'updates.upload.status': update_service.status,
            'updates.upload.append': update_service.append,
            'updates.upload.complete': update_service.complete,
            'configuration.backup': configuration_backup,
            'configuration.preview': preview_configuration_import,
            'configuration.apply': apply_configuration_import,
            'configuration.secure.backup': secure_configuration_backup,
            'configuration.secure.preview': preview_secure_configuration_import,
            'configuration.secure.apply': apply_secure_configuration_import,
            'settings.get': portal_settings,
            'settings.apply': update_portal_settings,
            'module_configuration.get': module_settings_json,
            'module_configuration.apply': update_module_settings,
            'certificates.upload': upload_certificate_file,
            'certificates.apply': validate_uploaded_certificates,
            'certificates.get': installed_certificate_details,
            'tasks.status': portal_task_status,
            'network.confirm': confirm_network_settings,
            'network.scan': wifi_recovery.cached_wifi_networks,
            'factory_reset.request': request_factory_default,
            'users.list': portal_auth.list_users,
            'users.add': portal_auth.add_user,
            'users.update': portal_auth.update_user,
            'users.remove': portal_auth.remove_user,
            'restart.status': pending_restart_status,
            'restart.request': request_pending_restart,
            'shutdown.request': request_device_shutdown,
        })
        web_portal_server = await portal_service.start(dependencies)
    except Exception as exc:
        logOutput('Local', 'Web portal', {'log': 'Failed to start - ' + str(exc)}, 'ERROR')
        return None

    logOutput(
        'Local',
        'Web portal',
        {'log': 'Listening on ' + scheme + '://' + portal_url_host + ':' + str(web_portal_port) + '/'},
        'INFO'
    )
    return web_portal_server


def confirm_network_settings():
    confirmed = credential_store.confirm_network_trial()
    if confirmed:
        logOutput(
            'Local', 'Network settings',
            {'log': 'Candidate network settings confirmed by authenticated portal login'},
            'INFO'
        )
    return confirmed


def request_factory_default(setup_password):
    credential_store.request_factory_reset(setup_password)
    logOutput(
        'Local', 'Factory default',
        {'log': 'Reset armed; immutable recovery will clear user data on reboot'},
        'INFO'
    )

    schedule_hardware_reset('factory_default_reboot')
    return True


async def network_trial_guard():
    await asyncio.sleep(max(30, int(network_trial_timeout_s)))
    if not credential_store.network_trial_pending():
        return
    credential_store.rollback_network_trial()
    logOutput(
        'Local', 'Network settings',
        {'log': 'Confirmation timed out; restored previous network settings'},
        'ERROR'
    )
    hardware_platform.reset()
            
            
async def _publish_message_now(msg, qosValue, logOnly, retain=False):
    
    
    if not logOnly:
        outputDevices[0]['output']['0'].toggle()
        try:
            if msg['payload'] is None:
                payload = b''
            elif isinstance(msg['payload'], bytes):
                payload = msg['payload']
            elif isinstance(msg['payload'], str):
                payload = msg['payload'].encode()
            else:
                payload = json.dumps(msg['payload']).encode()
            await client.publish(msg['topic'], payload, retain=retain, qos=qosValue)
            logOutput ('MQTT', 'Publish', msg, publish_logtype(msg))
            return True
        except Exception as exc:
            runtime_health.increment('mqtt_publish_failures')
            logOutput(
                'MQTT',
                'Publish',
                {
                    'payload': msg.get('payload'),
                    'topic': msg.get('topic'),
                    'log': 'Failed topic ' + str(msg.get('topic')) + ' - ' + str(exc)
                },
                'ERROR'
            )
            return False
        finally:
            outputDevices[0]['output']['0'].toggle()

    return True


async def publish_message(msg, qosValue, logOnly, retain=False):
    """Enqueue MQTT output without creating an unbounded task per message."""
    before = mqtt_publish_queue.stats()['dropped']
    mqtt_publish_queue.put(msg, qosValue, logOnly, retain)
    dropped = mqtt_publish_queue.stats()['dropped'] - before
    if dropped:
        runtime_health.increment('mqtt_publish_drops', dropped)
    await asyncio.sleep(0)
    return True


async def mqtt_publish_worker():
    while True:
        item = mqtt_publish_queue.get_nowait()
        if item is None:
            if hasattr(asyncio, 'sleep_ms'):
                await asyncio.sleep_ms(20)
            else:
                await asyncio.sleep(0.02)
            continue
        await _publish_message_now(
            item['data'], item['qos'], item['log_only'], item['retain']
        )
        await asyncio.sleep(0)


async def sync_ntp_time():
    global ntp_synced

    if ntp_synced:
        return True

    if ntptime is None:
        logOutput('Local', 'NTP', {'log': 'ntptime module not available'}, 'ERROR')
        return False

    if isinstance(ntp_servers, str):
        servers = (ntp_servers,)
    else:
        servers = ntp_servers

    if not servers:
        return False

    for server in servers:
        try:
            ntptime.host = server
            ntptime.settime()
            ntp_synced = True
            logOutput('Local', 'NTP', {'log': 'Time synced from ' + server}, 'INFO')
            return True
        except Exception as exc:
            logOutput('Local', 'NTP', {'log': 'Failed to sync from ' + server + ' - ' + str(exc)}, 'ERROR')
            await asyncio.sleep(1)

    return False


def local_input(inputDevice):
    """Wrapper that delegates to module-based handler."""
    logOutput ('Local', 'Switch', {'log':'Activity: ' + next(device for device in deviceObjects if device['uuid'] == inputDevice[1])['name']}, 'INFO')
    handle_local_input(inputDevice, deviceObjects, device_config, publish_message)


async def homeassistant_discovery():
    global last_discovery_count
    if not ha_discovery:
        logOutput('Local', 'HA Discovery', {'log': 'Skipped because ha_discovery is disabled'}, 'INFO')
        return
    last_discovery_count = await home_assistant_service.publish_discovery()


async def publish_availability(state):
    await home_assistant_service.publish_availability(state)
       
def device_config(devicetype, uuid, command, payload):
    device = next((d for d in outputDevices if d['uuid'] == uuid), None)
    if device is None:
        logOutput('Local', 'Device - Config', {'log': f'Device not found: {uuid}'}, 'ERROR')
        return {}
    
    msg_payload = {}

    if command == 'set' and 'driver' in device:
        try:
            result = device['driver'].set(payload)
            if isinstance(result, dict) and result.get('defer_publish'):
                return None
            msg_payload = device['driver'].get_state_payload()
        except Exception:
            msg_payload = {}

    data = {
        'payload': msg_payload,
        'topic': ha_state_topic(devicetype, deviceid, uuid),
        'log': 'HA Update: ' + deviceObjects[device['index']]['name']
    }

    return data


def module_command_completed(operation):
    """Publish the resulting state regardless of whether MQTT or API initiated it."""
    if not operation or operation.get('status') != 'complete':
        return
    result = operation.get('result') or {}
    state = result.get('state') if isinstance(result, dict) else None
    if state is None:
        return
    uuid = operation.get('module')
    device = next((item for item in deviceObjects if item.get('uuid') == uuid), None)
    if not device:
        return
    publish_wrapper({
        'payload': state,
        'topic': ha_state_topic(device['type']['class'], deviceid, uuid),
        'log': 'HA Update: ' + device.get('name', uuid),
    }, 0, False)


module_broker.add_listener(module_command_completed)



def decode_mqtt_value(value):
    if hasattr(value, 'decode'):
        return value.decode('utf-8')
    return str(value)


async def handle_mqtt_message(topic, payload, retained):
    msg_topic = decode_mqtt_value(topic)
    msg_payload_text = decode_mqtt_value(payload)

    if msg_topic == 'homeassistant/status':
        data = {
            'payload': msg_payload_text,
            'topic': msg_topic,
            'log': 'HA Status: ' + msg_payload_text
            }

        # Initial discovery is completed explicitly before the HTTPS portal is
        # opened. Ignore the retained birth message delivered on subscription;
        # live HA restarts still arrive with retained=False and trigger refresh.
        if msg_payload_text == 'online' and not retained:
            start_task('ha_discovery_status', homeassistant_discovery())

        logOutput ('MQTT', 'Received', data, 'INFO')
        return

    if msg_topic == ha_set_topic('button', deviceid, 'maint'):
        if retained:
            return
        command = msg_payload_text.strip().strip('"')
        if command == 'check_release' and release_manifest_url:
            start_task('release_check_ha', check_release_once())
        elif command == 'rollback_application':
            try:
                app_update.rollback_to_previous()
                await asyncio.sleep(1)
                hardware_platform.reset()
            except Exception as exc:
                logOutput('Local', 'Maintenance', {'log': 'Rollback failed - ' + str(exc)}, 'ERROR')
        elif command == 'reboot':
            await asyncio.sleep(1)
            hardware_platform.reset()
        return

    msg_payload = json.loads(msg_payload_text)

    data = {
            'payload': msg_payload,
            'topic': msg_topic,
            'log': msg_topic
        }

    logOutput ('MQTT', 'Received', data, 'INFO')

    msg_parts = msg_topic.split('/', 3)
    if len(msg_parts) != 4:
        return

    msg_topic_1, msg_topic_2, msg_topic_3, msg_topic_4 = msg_parts

    if msg_topic_1 == 'homeassistant':
        uuid = msg_topic_3[len(deviceid):len(msg_topic_3)]
        if msg_topic_4 == 'set':
            try:
                module_broker.submit(uuid, msg_payload, 'mqtt', msg_topic)
            except Exception as exc:
                logOutput(
                    'MQTT', 'Command',
                    {'log': 'Rejected module command - ' + str(exc)}, 'ERROR'
                )


async def messages(client):  # Respond to incoming messages
    logOutput('MQTT', 'Listener', {'log': 'Started subscribed message listener'}, 'INFO')

    async for topic, payload, retained in client.queue:
        try:
            await handle_mqtt_message(topic, payload, retained)
        except Exception as exc:
            try:
                msg_topic = decode_mqtt_value(topic)
                msg_payload = decode_mqtt_value(payload)
            except Exception:
                msg_topic = '<decode failed>'
                msg_payload = '<decode failed>'

            logOutput(
                'MQTT',
                'Received',
                {
                    'payload': msg_payload,
                    'topic': msg_topic,
                    'log': 'Message handling error on topic ' + msg_topic + ' - ' + str(exc)
                },
                'ERROR'
            )

        await asyncio.sleep(0)



async def configure_mqtt_connection(client):
    await sync_ntp_time()
    await client.subscribe('homeassistant/status', 1)
    logOutput('MQTT', 'Subscribe', {'log': 'Topic: homeassistant/status', 'topic': 'homeassistant/status', 'payload': None}, 'INFO')
    if ha_system_diagnostics:
        maintenance_topic = ha_set_topic('button', deviceid, 'maint')
        await client.subscribe(maintenance_topic, 1)
        logOutput('MQTT', 'Subscribe', {'log': 'Topic: ' + maintenance_topic, 'topic': maintenance_topic, 'payload': None}, 'INFO')

    for device in deviceObjects:
        devicetype = find_device_type(device)
        if device['uuid'] != '0000' and devicetype and devicetype['ha_subscribe']:
            topic = ha_set_topic(device['type']['class'], deviceid, device['uuid'])
            await client.subscribe(topic, 1)
            logOutput('MQTT', 'Subscribe', {'log': 'Topic: ' + topic, 'topic': topic, 'payload': None}, 'INFO')

    await publish_availability('online')
    await homeassistant_discovery()


async def up(client):  # Respond to connectivity being (re)established
    while True:
        await client.up.wait()
        client.up.clear()
        runtime_health.observe_wifi(reconnected=True)
        await configure_mqtt_connection(client)
        await asyncio.sleep(0)


def ssl_error_message(exc):
    detail = str(exc).strip()
    if not detail and getattr(exc, 'args', None):
        detail = ' '.join(str(arg) for arg in exc.args if arg)

    if not detail:
        detail = 'certificate validation failed'

    if 'validity has expired' in detail:
        detail += ' - renew the broker certificate or check the device clock/NTP.'

    if 'validity starts in the future' in detail:
        detail += ' - sync NTP before connecting or check the device clock.'

    if 'Common Name' in detail or 'expected CN' in detail:
        detail += ' - connect using the hostname covered by the certificate, or update the certificate SAN/CN.'

    return detail


network_service = NetworkService(
    lambda: {
        'address': wifi_ip_address(),
        'connected': wifi_ip_address() not in ('', '0.0.0.0'),
    },
    lambda: wifi_recovery.cached_wifi_networks(refresh=False),
    confirm_network_settings,
)
messaging_service = MessagingService(
    lambda topic, payload, retain=False, qos=0: publish_message(
        {'topic': topic, 'payload': payload, 'log': 'Service publish'},
        qos, False, retain
    ),
    status_getter=lambda: {
        'status': mqtt_connection_status(),
        'queue': mqtt_publish_queue.stats(),
    },
)
home_assistant_service = HomeAssistantService(
    deviceid,
    ha_devicename,
    deviceObjects,
    lambda: outputDevices + inputDevices,
    find_device_type,
    publish_message,
    logOutput,
    web_portal_url,
    module_health_payload,
    system_enabled=ha_system_diagnostics,
    system_discovery=system_info_discovery,
    system_state=system_info_payload,
    maintenance_discovery=maintenance_discovery,
)
application_context.register('network', network_service)
application_context.register('messaging', messaging_service)
application_context.register('home_assistant', home_assistant_service)
application_context.seal((
    'events', 'modules', 'portal', 'updates', 'network', 'messaging',
    'home_assistant'
))



async def main(client):
    global watchdog, release_available, release_check_status

    application_context.lifecycle.transition('starting')
    application_context.state.set('phase', 'starting')
    start_local_display()
    start_task('module_command_broker', module_broker.run(), main_device_task=True)

    status_led = outputDevices[0]['output']['0']
    hardware_platform.set_status_led_state(status_led, 'wifi')

    try:
        logOutput('MQTT', 'Connect', {'log': 'Connect WiFi before NTP sync'}, 'INFO')
        await client.wifi_connect(quick=True)
        application_context.lifecycle.transition('network-ready')
        application_context.state.set('network', 'online')
        try:
            runtime_health.observe_wifi(network.WLAN(network.STA_IF).status('rssi'))
        except Exception:
            pass
    except (OSError, ValueError) as exc:
        application_context.lifecycle.transition('failed', 'Wi-Fi: ' + str(exc))
        logOutput('WiFi', 'Connect', {'log': 'Connection error: ' + str(exc)}, 'ERROR')
        set_main_device_error()
        if credential_store.network_trial_pending():
            credential_store.rollback_network_trial()
            logOutput(
                'Local', 'Network settings',
                {'log': 'Connection failed; restored previous network settings'},
                'ERROR'
            )
            hardware_platform.reset()
            return
        trials_pending = (
            app_update.update_status().get('status') in ('trial', 'committing') or
            firmware_update.update_status().get('status') == 'trial'
        )
        if wifi_recovery_enabled and not trials_pending:
            request_core_recovery = getattr(recovery_boot, 'request_recovery', None)
            if request_core_recovery:
                request_core_recovery('Wi-Fi station connection failed: ' + str(exc))
            hardware_platform.reset()
        return

    portal_started = await start_admin_portal()
    if web_portal_enabled and portal_started is None:
        application_context.lifecycle.transition('failed', 'portal failed to start')
        set_main_device_error()
        if credential_store.network_trial_pending():
            credential_store.rollback_network_trial()
            logOutput(
                'Local', 'Network settings',
                {'log': 'Portal failed to start; restored previous network settings'},
                'ERROR'
            )
            hardware_platform.reset()
        if (
            app_update.update_status().get('status') == 'trial' or
            firmware_update.update_status().get('status') == 'trial'
        ):
            logOutput(
                'Local', 'Update health',
                {'log': 'Portal health check failed; update will roll back'}, 'ERROR'
            )
        return
    application_context.lifecycle.transition(
        'portal-ready', 'listening' if portal_started is not None else 'disabled'
    )
    application_context.state.set(
        'portal', 'listening' if portal_started is not None else 'disabled'
    )
    if portal_started is not None:
        hardware_platform.set_status_led_state(status_led, 'ok')
    if credential_store.network_trial_pending():
        start_task('network_trial_guard', network_trial_guard())

    # Wi-Fi and the authenticated local portal (when enabled) are the startup
    # health boundary. MQTT remains an external, portal-repairable service.
    mark_application_healthy = getattr(
        recovery_boot, 'mark_application_healthy', None
    )
    if mark_application_healthy:
        mark_application_healthy()
    firmware_confirmed = False
    application_confirmed = False
    try:
        if firmware_update.confirm_update():
            firmware_confirmed = True
            logOutput(
                'Local', 'Base firmware',
                {'log': 'OTA partition confirmed after portal health check'}, 'INFO'
            )
    except Exception as exc:
        logOutput('Local', 'Base firmware', {'log': 'Could not confirm OTA partition - ' + str(exc)}, 'ERROR')
    if app_update.confirm_update():
        application_confirmed = True
        logOutput('Local', 'Application update', {'log': 'Update confirmed healthy'}, 'INFO')
    if universal_update.confirm_update():
        logOutput(
            'Local', 'Universal update',
            {'log': 'Core and application update confirmed healthy'}, 'INFO'
        )
    cancel_recovery_trial_deadline_if_healthy()

    await sync_ntp_time()
    await start_module_api()
    application_context.lifecycle.transition('services-ready')
    application_context.state.set('api', 'ready')
    start_task('fleet_policy_monitor', fleet_policy_monitor())
    if remote_syslog.active:
        start_task('remote_syslog', remote_syslog.run())
    start_task('certificate_alerts', certificate_alert_monitor())

    paired = update_orchestrator.refresh(
        app_update.running_release_sequence(),
        firmware_update.running_release_sequence(),
        app_update.running_version(device_settings.ha_device_info.get('sw', '')),
        firmware_update.running_version(hardware_platform.runtime_version())
    )
    if firmware_confirmed:
        runtime_health.record_update_result(
            'firmware', 'confirmed',
            firmware_update.running_version(hardware_platform.runtime_version())
        )
    if application_confirmed:
        runtime_health.record_update_result(
            'application', 'confirmed',
            app_update.running_version(device_settings.ha_device_info.get('sw', ''))
        )
    if paired and paired.get('status') != 'complete':
        release_available = update_orchestrator.next_release() or {}
        if release_available:
            progress = update_orchestrator.status()
            release_check_status = (
                'Paired update step ' + str(progress.get('step', 0)) +
                ' of ' + str(progress.get('total_steps', 0))
            )
            if release_auto_download:
                try:
                    await download_release_once()
                except Exception as exc:
                    update_orchestrator.mark_failed(exc)
                    runtime_health.record_update_result(
                        release_available.get('type', 'release'), 'failed',
                        release_available.get('version', ''), str(exc)
                    )

    if certificate_config.get('mode') == 'acme':
        start_task(
            'certificate_renewal',
            certificate_manager.renewal_monitor(
                certificate_config, device_settings.service_ca_path('mqtt'),
                logOutput, schedule_portal_certificate_reload
            )
        )

    mqtt_started = False
    if mqtt_configured and mqtt_tls_ready:
        try:
            await client.connect()
            client.up.clear()
            start_task('mqtt_publish_worker', mqtt_publish_worker(), main_device_task=True)
            await configure_mqtt_connection(client)
            mqtt_started = True
        except ValueError as exc:
            logOutput('MQTT', 'Connect', {'log': 'SSL error: ' + ssl_error_message(exc)}, 'ERROR')
            set_main_device_error()
        except OSError as exc:
            logOutput('MQTT', 'Connect', {'log': 'Connection error: ' + str(exc)}, 'ERROR')
            set_main_device_error()
    elif not mqtt_configured:
        logOutput(
            'MQTT', 'Connect',
            {'log': 'Not configured; use Device Portal > Settings'},
            'INFO'
        )
    else:
        logOutput(
            'MQTT', 'Connect',
            {'log': 'Not started; install a trusted CA in Maintenance > Certificates'},
            'ERROR'
        )
        set_main_device_error()

    if mqtt_started:
        application_context.state.set('mqtt', 'online')
        for coroutine in (up, messages):
            start_task(coroutine.__name__, coroutine(client), main_device_task=True)

    if release_manifest_url:
        start_task('release_monitor', release_monitor())

    if watchdog_timeout_ms and WDT:
        watchdog_timeout = hardware_platform.watchdog_timeout(watchdog_timeout_ms)
        if watchdog_timeout != watchdog_timeout_ms:
            logOutput(
                'Local',
                'Watchdog',
                {'log': 'Requested ' + str(watchdog_timeout_ms) + ' ms, using max ' + str(watchdog_timeout) + ' ms'},
                'INFO'
            )
        watchdog = WDT(timeout=watchdog_timeout)
        credential_security.set_progress_callback(service_password_calculation)
        logOutput('Local', 'Watchdog', {'log': 'Enabled: ' + str(watchdog_timeout) + ' ms'}, 'INFO')

    application_context.lifecycle.transition('running')
    application_context.state.set('phase', 'running')
    while True:
        if watchdog:
            watchdog.feed()
        if gc and hasattr(gc, 'mem_free'):
            runtime_health.observe_heap(gc.mem_free())
        try:
            runtime_health.observe_wifi(network.WLAN(network.STA_IF).status('rssi'))
        except Exception:
            pass
        status_led = outputDevices[0]['output']['0']
        colour, solid = hardware_platform.status_led_mode(
            main_device_error, modules_have_issues()
        )
        if solid:
            set_status_led_colour(status_led, colour)
            status_led(1)
            await asyncio.sleep(6)
            continue
        set_status_led_colour(status_led, colour)
        status_led(0)
        await asyncio.sleep(5)
        if main_device_error:
            continue
        # If WiFi is down the following will pause for the duration.
        status_led(1)
        await asyncio.sleep(1)
        if main_device_error:
            continue
        status_led(0)
        if watchdog:
            watchdog.feed()


mqtt_tls_ready = not mqtt_configured
cacert = None
if mqtt_configured:
    logOutput('MQTT', 'Connect', {'log': 'Load CA trust certificate'}, 'INFO')
    try:
        cacert = device_settings.service_ca_bytes('mqtt', required=True)
        mqtt_tls_ready = True
        logOutput('MQTT', 'Connect', {'log': 'Loaded CA trust certificate'}, 'INFO')
    except Exception as exc:
        mqtt_tls_ready = False
        logOutput(
            'MQTT', 'Connect',
            {'log': 'Disabled until a trusted CA is installed - ' + str(exc)},
            'ERROR'
        )

config['client_id'] = deviceid
config['will'] = (ha_availability_topic(deviceid), b'offline', True, 0)
config['ssl_params'] = (
    {
        'server_side': False, 'key': None, 'cert': None,
        'cadata': cacert, 'cert_reqs': ssl.CERT_REQUIRED,
        'server_hostname': config['server']
    }
    if mqtt_tls_ready and mqtt_configured else {}
)
# mqtt_as MsgQueue keeps one slot empty to distinguish full from empty, so a
# queue_len of 1 has no usable capacity and subscribed messages are discarded.
config["queue_len"] = 8

MQTTClient.DEBUG = loglevel == 'DEBUG'

client = MQTTClient(config)


def mqtt_debug_output(msg, *args):
    try:
        detail = msg % args
    except Exception:
        detail = str(msg)
    logOutput('MQTT', 'Debug', {'log': detail}, 'DEBUG')


client.dprint = mqtt_debug_output


def trace_mqtt_queue_put(topic, payload, retained):
    try:
        msg_topic = decode_mqtt_value(topic)
        msg_payload = decode_mqtt_value(payload)
        logOutput(
            'MQTT',
            'Queue',
            {
                'payload': msg_payload,
                'topic': msg_topic,
                'log': 'Topic: ' + msg_topic
            },
            'DEBUG'
        )
    except Exception as exc:
        logOutput('MQTT', 'Queue', {'log': 'Trace error: ' + str(exc)}, 'ERROR')

    mqtt_queue_put(topic, payload, retained)


mqtt_queue_put = client.queue.put
client.queue.put = trace_mqtt_queue_put


# Helper for drivers to publish via main publish_message
def publish_wrapper(data, qosValue, logOnly, retain=False):
    before = mqtt_publish_queue.stats()['dropped']
    mqtt_publish_queue.put(data, qosValue, logOnly, retain)
    dropped = mqtt_publish_queue.stats()['dropped'] - before
    if dropped:
        runtime_health.increment('mqtt_publish_drops', dropped)

# Import module settings, validate, associate GPIO inputs/outputs, and initialise

i = 1

logOutput ('Local', 'Device', {'log':'Importing module settings file: ' + moduleSettingsFile}, 'INFO')

try:
    moduleSettings = device_settings.load_required_json(
        moduleSettingsFile, recover_previous=True
    )
except RuntimeError as exc:
    if 'not found' not in str(exc):
        logOutput('Local', 'Device', {'log': str(exc)}, 'ERROR')
        raise
    moduleSettings = {'devices': []}
    logOutput(
        'Local', 'Device',
        {'log': 'No module settings file; starting with no configured modules'},
        'INFO'
    )
    
logOutput ('Local', 'Device', {'log':'Imported module settings file: ' + moduleSettingsFile}, 'INFO')

deviceTypes = configure_for_devices(moduleSettings.get('devices', ()))

validation_errors = validate_device_config(moduleSettings, deviceTypes)
for validation_error in validation_errors:
    logOutput('Local', 'Device validation', {'log': validation_error}, 'ERROR')

if validation_errors:
    raise RuntimeError('Invalid module settings file: ' + moduleSettingsFile)
        
for device in moduleSettings['devices']:
    if deviceValidation(device):
        logOutput('Local', 'Add device', {'log': device['name'] + ' (' + device['type']['class'] + ':' + device['type']['subclass'] + ')'}, 'INFO')

        deviceObjects.append(device)

        # Delegate GPIO/device wiring to modular loader
        device_char = setup_device(device, i)
        if device_char:
            if device_char.get('setup_error'):
                failedModules.append(device_char)
            elif 'output' in device_char:
                outputDevices.append(device_char)
            if 'input' in device_char:
                # Wire callbacks/encoders for switches (maintain previous behavior)
                if device['type']['class'] == 'switch':
                    if device['type']['subclass'] == 'onoff':
                        device_char['input']['0'].press_func(local_input, (('onoff', device_char['uuid'], 0),))
                    if device['type']['subclass'] == 'dimmer':
                        def dimmer_callback(value, change, dev_type, dev_uuid):
                            local_input((dev_type, dev_uuid, change))
                        Encoder(device_char['input']['clk'], device_char['input']['dt'], div=device['entities']['0']['div'], callback=dimmer_callback, args=('dimmer', device_char['uuid']))
                        device_char['input']['sw'].press_func(local_input, (('onoff', device_char['uuid'], 0),))

                inputDevices.append(device_char)
            if 'output' not in device_char and 'input' not in device_char and 'driver' in device_char:
                outputDevices.append(device_char)

        # If driver exists, publish discovery and initial state; start sensor loops
        i += 1

        # Initialise local devices
        deviceType = find_device_type(device)

        payload = {}

        if device['uuid'] != '0000' and deviceType and deviceType['local_init']:
            for e in device['entities']:
                if device['type']['class'] == 'light':
                    payload = device['entities'][str(e)]
                elif device['type']['class'] == 'sensor':
                    payload[device['entities'][str(e)]['class']] = device['entities'][str(e)]['value']

            device_config(device['type']['class'], device['uuid'], 'set', payload)
            logOutput('Local', 'Initialise device', {'log': device['name']}, 'INFO')

        if device_char and 'driver' in device_char and device['type']['class'] == 'sensor':
            try:
                device_char['driver'].start(publish_wrapper, deviceid, logOutput)
            except Exception as exc:
                logOutput('Local', 'Start device', {'log': device['name'] + ' - ' + str(exc)}, 'ERROR')
                    

try:
    asyncio.run(main(client))
except Exception as exc:
    runtime_health.observe(
        'last_startup_exception', 'main: ' + str(exc), force=True
    )
    runtime_health.record_event(
        'startup_exception', 'main: ' + str(exc), force=True
    )
    raise
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
