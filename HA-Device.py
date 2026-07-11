import ssl
import time
from binascii import hexlify
import json
import secrets
import settings_loader as device_settings
try:
    import network
except ImportError:
    network = None
from machine import Pin, unique_id
try:
    from machine import WDT
except ImportError:
    WDT = None
from primitives import Encoder
from mqtt_as import MQTTClient, config
import asyncio
from device_modules import setup_device
from device_modules.loader import get_device_types
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
    homeassistant_origin_info
)
from device_modules.validation import validate_device_config
from device_modules.logging import set_log_output
from web_portal import start_web_portal
from local_display import LocalDisplayService

try:
    import ntptime
except ImportError:
    ntptime = None



# Local configuration

ca_cert_path = device_settings.ca_cert_path

config['ssid'] = secrets.wifi_ssid
config['wifi_pw'] = secrets.wifi_password


config['server'] = secrets.mqtt_server
config['user'] = secrets.mqtt_username
config['password'] = secrets.mqtt_password
config['ssl'] = secrets.mqtt_ssl

ha_discovery = device_settings.ha_discovery
ha_devicename = device_settings.ha_device_name
moduleSettingsFile = device_settings.module_settings_file


# Module settings

hardware_deviceid = hexlify(unique_id()).decode()
deviceid = hardware_deviceid + '_' + ha_safe_id(ha_devicename)

ntp_servers = device_settings.ntp_servers
ha_system_diagnostics = device_settings.ha_system_diagnostics
ha_discovery_cleanup_legacy_identity = device_settings.ha_discovery_cleanup_legacy_identity

loglevels = ['ERROR', 'INFO', 'DEBUG']
loglevel = device_settings.loglevel
watchdog_timeout_ms = device_settings.watchdog_timeout_ms
watchdog_max_timeout_ms = 8000
watchdog = None
ntp_synced = False
web_portal_server = None
web_portal_enabled = device_settings.web_portal_enabled
web_portal_https = device_settings.web_portal_https
web_portal_host = device_settings.web_portal_host
web_portal_port = device_settings.web_portal_port
if web_portal_port is None:
    web_portal_port = 8443 if web_portal_https else 8080
web_portal_token = getattr(secrets, 'web_portal_token', '')
web_portal_cert_path = device_settings.web_portal_cert_path
web_portal_key_path = device_settings.web_portal_key_path
web_portal_log_refresh_s = device_settings.web_portal_log_refresh_s
web_portal_value_refresh_s = device_settings.web_portal_value_refresh_s
web_log_buffer_lines = device_settings.web_log_buffer_lines
web_log_line_max_chars = device_settings.web_log_line_max_chars
log_buffer = []
local_display_config = device_settings.local_display
local_display_service = None
last_discovery_count = 0


def ticks_ms():
    if hasattr(time, 'ticks_ms'):
        return time.ticks_ms()
    return int(time.time() * 1000)


def ticks_diff(end, start):
    if hasattr(time, 'ticks_diff'):
        return time.ticks_diff(end, start)
    return end - start


boot_ms = ticks_ms()

# Device types will be loaded from device modules
deviceTypes = []

deviceObjects = [
    # System LED
    {'name': 'S1', 'uuid': '0000', 'type': {'class': 'light', 'subclass': 'onoff'}, 'entities': {'0': {'state': 'OFF'}}, 'gpio': {'activeHigh': True, 'output': {'0': 'LED'}}},
]

outputDevices = [
    # System LED
    {'uuid': '0000', 'index': 0, 'output': {'0': Pin('LED', Pin.OUT)}}    
]

inputDevices = []



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
    current_time = time.localtime()
    
    timestamp = "{:04}{:02}{:02} {:02}{:02}{:02}".format(current_time[0], current_time[1], current_time[2], current_time[3], current_time[4], current_time[5])
    
    if data.get('force') or loglevels.index(logtype) <= loglevels.index(loglevel):
        
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

        remember_log(log)


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


def get_loglevel():
    return loglevel


def set_loglevel(level):
    global loglevel
    if level in loglevels:
        loglevel = level
        MQTTClient.DEBUG = loglevel == 'DEBUG'


def start_task(name, coroutine):
    async def runner():
        try:
            logOutput('Local', 'Task', {'log': 'Started ' + name}, 'DEBUG')
            await coroutine
        except Exception as exc:
            logOutput('Local', 'Task', {'log': name + ' stopped - ' + str(exc)}, 'ERROR')

    return asyncio.create_task(runner())


set_log_output(logOutput)

logOutput(
    'Local',
    'Device',
    {'log': 'Imported device settings file: ' + device_settings.DEVICE_SETTINGS_FILE},
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
    if not web_portal_enabled or not web_portal_token:
        return None

    scheme = 'https' if web_portal_https else 'http'
    host = wifi_ip_address()
    return (
        scheme + '://' + host + ':' + str(web_portal_port) +
        '/?token=' + web_portal_token
    )


def uptime_seconds():
    return max(0, int(ticks_diff(ticks_ms(), boot_ms) / 1000))


def mqtt_connection_status():
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

    return {
        'device_name': ha_devicename,
        'wifi_ip': wifi_ip_address(),
        'mqtt': mqtt_connection_status(),
        'config': moduleSettingsFile,
        'loglevel': get_loglevel(),
        'web_portal': web_portal_enabled,
        'uptime_s': uptime_seconds(),
        'discovery_count': last_discovery_count,
        'alerts': alerts
    }


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
    return local_display_status()


def module_summaries():
    summaries = []
    for device_char in outputDevices:
        if device_char.get('uuid') == '0000':
            continue

        device = next((d for d in deviceObjects if d.get('uuid') == device_char.get('uuid')), None)
        if not device:
            continue

        driver = device_char.get('driver')
        state = {}
        diagnostics = {}
        calibratable = False
        if driver:
            try:
                raw_state = driver.get_state_payload()
            except Exception as exc:
                raw_state = {'error': str(exc)}

            diagnostic_keys = set()
            for entity_id in device.get('entities', {}):
                entity = device['entities'][str(entity_id)]
                key = entity.get('key', entity.get('class', str(entity_id)))
                if entity.get('entity_category') == 'diagnostic':
                    diagnostic_keys.add(key)

            for key in raw_state:
                if key in diagnostic_keys:
                    diagnostics[key] = raw_state[key]
                else:
                    state[key] = raw_state[key]

            if hasattr(driver, 'diagnostics_payload'):
                try:
                    health = driver.diagnostics_payload()
                except Exception:
                    health = {}
                for key in health:
                    diagnostics['module_' + key] = health[key]
            calibratable = hasattr(driver, 'set_calibration') and device.get('type', {}).get('subclass') == 'Grove-AC-Voltage'

        summaries.append({
            'uuid': device.get('uuid', ''),
            'name': device.get('name', ''),
            'type': device.get('type', {}).get('subclass', device.get('type', {}).get('class', '')),
            'state': state,
            'diagnostics': diagnostics,
            'calibratable': calibratable
        })
    return summaries


def system_info_payload():
    return {
        'firmware_version': device_settings.ha_device_info.get('sw', ''),
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


def module_health_discovery(device):
    payloads = {}
    for key in ('module_last_ok', 'module_last_error', 'module_last_read_ms', 'module_last_publish_age_s', 'module_consecutive_errors'):
        payloads[key] = {
            '~': ha_device_topic(device['type']['class'], deviceid, device['uuid']),
            'stat_t': '~/state',
            'uniq_id': ha_unique_id(deviceid, device['uuid'], key),
            'name': device['name'] + ' ' + key,
            'value_template': "{{ value_json[" + repr(key) + "] }}",
            'availability_topic': ha_availability_topic(deviceid),
            'payload_available': 'online',
            'payload_not_available': 'offline',
            'entity_category': 'diagnostic',
            'en': False,
            'dev': homeassistant_device_info(deviceid, ha_devicename, device.get('_portal_url')),
            'o': homeassistant_origin_info()
        }
    return payloads


def legacy_identity_cleanup_topics(device, payload_discovery):
    if not ha_discovery_cleanup_legacy_identity or hardware_deviceid == deviceid:
        return []

    topics = []
    for entity_id, payload in payload_discovery.items():
        component = payload.get('_component', device['type']['class'])
        topics.append(ha_config_topic(component, hardware_deviceid, device['uuid'], entity_id))
    return topics


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
        result = driver.set_calibration({'known_voltage': known_voltage})
        if isinstance(result, dict) and result.get('ok'):
            return 'Calibration set to ' + str(result.get('calibration')) + ' for module ' + str(uuid)
        if isinstance(result, dict):
            return 'Calibration failed: ' + str(result.get('error', result))
        return 'Calibration failed'

    return 'Unknown action'


async def start_admin_portal():
    global web_portal_server

    if not web_portal_enabled:
        return None

    if not web_portal_token:
        logOutput('Local', 'Web portal', {'log': 'Disabled: missing web_portal_token in secrets.py'}, 'ERROR')
        return None

    settings = {
        'https': web_portal_https,
        'host': web_portal_host,
        'port': web_portal_port,
        'token': web_portal_token,
        'cert_path': web_portal_cert_path,
        'key_path': web_portal_key_path,
        'levels': tuple(loglevels),
        'log_refresh_ms': web_portal_log_refresh_s * 1000,
        'value_refresh_ms': web_portal_value_refresh_s * 1000
    }

    scheme = 'https' if web_portal_https else 'http'
    portal_url_host = wifi_ip_address()
    logOutput(
        'Local',
        'Web portal',
        {'log': 'Starting on ' + web_portal_host + ':' + str(web_portal_port)},
        'INFO'
    )

    try:
        web_portal_server = await start_web_portal(
            settings,
            get_log_buffer,
            get_loglevel,
            set_loglevel,
            logOutput,
            portal_status,
            module_summaries,
            portal_action
        )
    except Exception as exc:
        logOutput('Local', 'Web portal', {'log': 'Failed to start - ' + str(exc)}, 'ERROR')
        return None

    logOutput(
        'Local',
        'Web portal',
        {'log': 'Listening on ' + scheme + '://' + portal_url_host + ':' + str(web_portal_port) + '/?token=<token>'},
        'INFO'
    )
    return web_portal_server
            
            
async def publish_message(msg, qosValue, logOnly, retain=False):
    
    
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
        except Exception as exc:
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
        finally:
            outputDevices[0]['output']['0'].toggle()


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

    device_info_added = False
    discovery_count = 0

    logOutput('Local', 'HA Discovery', {'log': 'Started'}, 'INFO')

    def find_device_char(uuid):
        for d in outputDevices:
            if d.get('uuid') == uuid:
                return d
        for d in inputDevices:
            if d.get('uuid') == uuid:
                return d
        return None

    for device in deviceObjects:
        devicetype = find_device_type(device)

        if device['uuid'] != '0000' and devicetype and devicetype['ha_discovery']:
            payload_discovery = {}
            payload_entities = {}

            device_char = find_device_char(device['uuid'])
            cleanup_topics = []
            if device_char and 'driver' in device_char:
                try:
                    portal_url = web_portal_url()
                    if portal_url:
                        device['_portal_url'] = portal_url
                    elif '_portal_url' in device:
                        del device['_portal_url']
                    if hasattr(device_char['driver'], 'prepare_discovery'):
                        await device_char['driver'].prepare_discovery()
                    payload_discovery, payload_entities = device_char['driver'].get_discovery_payloads(deviceid, ha_devicename)
                    health_payload = module_health_payload(device_char['driver'])
                    if health_payload:
                        payload_entities.update(health_payload)
                        payload_discovery.update(module_health_discovery(device))
                        cleanup_topics.append(ha_config_topic(
                            device['type']['class'],
                            deviceid,
                            device['uuid'],
                            'module_last_publish_ms'
                        ))
                        if ha_discovery_cleanup_legacy_identity:
                            cleanup_topics.append(ha_config_topic(
                                device['type']['class'],
                                hardware_deviceid,
                                device['uuid'],
                                'module_last_publish_ms'
                            ))
                    if hasattr(device_char['driver'], 'discovery_cleanup_topics'):
                        cleanup_topics = device_char['driver'].discovery_cleanup_topics(
                            deviceid,
                            payload_discovery.keys()
                        )
                        if ha_discovery_cleanup_legacy_identity:
                            cleanup_topics.extend(device_char['driver'].discovery_cleanup_topics(
                                hardware_deviceid,
                                payload_discovery.keys()
                            ))
                    cleanup_topics.extend(legacy_identity_cleanup_topics(device, payload_discovery))
                except Exception as exc:
                    logOutput(
                        'Local',
                        'HA Discovery',
                        {'log': device['name'] + ' - ' + str(exc)},
                        'ERROR'
                    )
                    payload_discovery = {}
                    payload_entities = {}
                    cleanup_topics = []
            else:
                logOutput(
                    'Local',
                    'HA Discovery',
                    {'log': device['name'] + ' - no driver available for discovery'},
                    'ERROR'
                )

            if not device_info_added and payload_discovery:
                first_discovery_id = next(iter(payload_discovery))
                if "dev" not in payload_discovery[first_discovery_id]:
                    payload_discovery[first_discovery_id].update({
                        "dev": homeassistant_device_info(deviceid, ha_devicename, device.get('_portal_url'))
                    })
                device_info_added = True

            for topic in cleanup_topics:
                data = {
                    'payload': None,
                    'topic': topic,
                    'log': 'HA Discovery cleanup: ' + device['name'] + ' - ' + topic
                }
                await publish_message(data, 0, False, True)

            device_discovery_count = 0
            for i in payload_discovery:
                payload = payload_discovery[i].copy()
                topic = payload.pop('_topic', None)
                component = payload.pop('_component', device['type']['class'])
                if topic is None:
                    topic = ha_config_topic(component, deviceid, device['uuid'], i)
                data = {
                    'payload': payload,
                    'topic': topic,
                    'log': 'HA Discovery entity: ' + device['name'] + ' ' + str(i)
                }
                await publish_message(data, 0, False, True)
                discovery_count += 1
                device_discovery_count += 1

            if device_discovery_count:
                logOutput(
                    'Local',
                    'HA Discovery',
                    {'log': device['name'] + ' - ' + str(device_discovery_count) + ' config payloads'},
                    'INFO'
                )

            await asyncio.sleep(1)

            data = {
                'payload': payload_entities,
                'topic': ha_state_topic(device['type']['class'], deviceid, device['uuid']),
                'log': 'HA Update: ' + device['name']
            }
            await publish_message(data, 0, False)

    if ha_system_diagnostics:
        system_discovery_count = 0
        for key, payload in system_info_discovery().items():
            if ha_discovery_cleanup_legacy_identity and hardware_deviceid != deviceid:
                data = {
                    'payload': None,
                    'topic': ha_config_topic('sensor', hardware_deviceid, 'sys', key),
                    'log': 'HA Discovery cleanup: system diagnostics - ' + str(key)
                }
                await publish_message(data, 0, False, True)
            data = {
                'payload': payload,
                'topic': ha_config_topic('sensor', deviceid, 'sys', key),
                'log': 'HA Discovery entity: system diagnostics ' + str(key)
            }
            await publish_message(data, 0, False, True)
            discovery_count += 1
            system_discovery_count += 1

        data = {
            'payload': system_info_payload(),
            'topic': ha_state_topic('sensor', deviceid, 'sys'),
            'log': 'HA Update: system diagnostics'
        }
        await publish_message(data, 0, False)
        logOutput(
            'Local',
            'HA Discovery',
            {'log': 'system diagnostics - ' + str(system_discovery_count) + ' config payloads'},
            'INFO'
        )

    last_discovery_count = discovery_count
    logOutput('Local', 'HA Discovery', {'log': 'Completed with ' + str(discovery_count) + ' config payloads'}, 'INFO')


async def publish_availability(state):
    if state == 'online' and ha_discovery_cleanup_legacy_identity and hardware_deviceid != deviceid:
        data = {
            'payload': 'offline',
            'topic': ha_availability_topic(hardware_deviceid),
            'log': 'Legacy availability: offline'
        }
        await publish_message(data, 0, True, True)

    data = {
        'payload': state,
        'topic': ha_availability_topic(deviceid),
        'log': 'Availability: ' + state
    }
    await publish_message(data, 0, False, True)
       
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

        if msg_payload_text == 'online':
            start_task('ha_discovery_status', homeassistant_discovery())

        logOutput ('MQTT', 'Received', data, 'INFO')
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
        data = device_config(msg_topic_2, msg_topic_3[len(deviceid):len(msg_topic_3)], msg_topic_4, msg_payload)
        if data:
            start_task('mqtt_set_publish', publish_message(data, 0, False))


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



async def up(client):  # Respond to connectivity being (re)established
       
    while True:
    
        await client.up.wait()  # Wait on an Event
        client.up.clear()

        await sync_ntp_time()
        
        await client.subscribe('homeassistant/status', 1)
        
        logOutput ('MQTT', 'Subscribe', {'log':'Topic: homeassistant/status', 'topic': 'homeassistant/status', 'payload': None}, 'INFO')
    
        for device in deviceObjects:
            
            devicetype = find_device_type(device)

            if device['uuid'] != '0000' and devicetype and devicetype['ha_subscribe']:
            
                topic = ha_set_topic(device['type']['class'], deviceid, device['uuid'])
                await client.subscribe(topic, 1)
            
                logOutput ('MQTT', 'Subscribe', {'log':'Topic: ' + topic, 'topic': topic, 'payload': None}, 'INFO')   
            
        await publish_availability('online')
        start_task('ha_discovery_connect', homeassistant_discovery())

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



async def main(client):
    global watchdog

    start_local_display()

    try:
        logOutput('MQTT', 'Connect', {'log': 'Connect WiFi before NTP sync'}, 'INFO')
        await client.wifi_connect(quick=True)
        await sync_ntp_time()
        await start_admin_portal()
        await client.connect()
    except ValueError as exc:
        logOutput('MQTT', 'Connect', {'log': 'SSL error: ' + ssl_error_message(exc)}, 'ERROR')
        return
    except OSError as exc:
        logOutput('MQTT', 'Connect', {'log': 'Connection error: ' + str(exc)}, 'ERROR')
        return

    for coroutine in (up, messages):
        start_task(coroutine.__name__, coroutine(client))

    if watchdog_timeout_ms and WDT:
        watchdog_timeout = min(watchdog_timeout_ms, watchdog_max_timeout_ms)
        if watchdog_timeout != watchdog_timeout_ms:
            logOutput(
                'Local',
                'Watchdog',
                {'log': 'Requested ' + str(watchdog_timeout_ms) + ' ms, using max ' + str(watchdog_timeout) + ' ms'},
                'INFO'
            )
        watchdog = WDT(timeout=watchdog_timeout)
        logOutput('Local', 'Watchdog', {'log': 'Enabled: ' + str(watchdog_timeout) + ' ms'}, 'INFO')
    
    while True:
        if watchdog:
            watchdog.feed()
        await asyncio.sleep(5)
        # If WiFi is down the following will pause for the duration.
        outputDevices[0]['output']['0'](1)
        await asyncio.sleep(1)
        outputDevices[0]['output']['0'](0)
        if watchdog:
            watchdog.feed()


logOutput ('MQTT', 'Connect', {'log':'Load CA Trust Certificate'}, 'INFO')
    
with open(ca_cert_path, 'rb') as f:
    cacert = f.read()
        
logOutput ('MQTT', 'Connect', {'log':'Loaded CA Trust Certificate'}, 'INFO')

# Load device types from registered modules
deviceTypes = get_device_types()

config['client_id'] = deviceid
config['will'] = (ha_availability_topic(deviceid), b'offline', True, 0)
config['ssl_params'] = {'server_side':False, 'key':None, 'cert':None, 'cadata':cacert, 'cert_reqs':ssl.CERT_REQUIRED, 'server_hostname': config['server']}
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
    try:
        start_task('driver_publish', publish_message(data, qosValue, logOnly, retain))
    except Exception:
        pass

# Import module settings, validate, associate GPIO inputs/outputs, and initialise

i = 1

logOutput ('Local', 'Device', {'log':'Importing module settings file: ' + moduleSettingsFile}, 'INFO')

try:
    moduleSettings = device_settings.load_required_json(moduleSettingsFile)
except RuntimeError as exc:
    logOutput('Local', 'Device', {'log': str(exc)}, 'ERROR')
    raise
    
logOutput ('Local', 'Device', {'log':'Imported module settings file: ' + moduleSettingsFile}, 'INFO')

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
            if 'output' in device_char:
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
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
