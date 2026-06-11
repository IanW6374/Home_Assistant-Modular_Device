import ssl
import time
from binascii import hexlify
import json
import secrets
import device_settings
from machine import Pin, unique_id
from primitives import Encoder
from mqtt_as import MQTTClient, config
import asyncio
from device_modules import setup_device
from device_modules.loader import get_device_types
from device_modules.base import handle_local_input, homeassistant_device_info

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

deviceConfigFile = device_settings.deviceConfigFile


# Device Configuration

deviceid = hexlify(unique_id()).decode()

ha_discovery = device_settings.ha_discovery
ha_devicename = device_settings.ha_devicename
ntp_servers = getattr(device_settings, 'ntp_servers', ('pool.ntp.org',))

loglevels = ['ERROR', 'INFO', 'DEBUG']
loglevel = 'INFO'
mqtt_debug = getattr(device_settings, 'mqtt_debug', True)

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
    
    if loglevels.index(logtype) <= loglevels.index(loglevel):
        
        log = timestamp + '  ' + mode + ': ' + action + ' - ' + data['log']
        
        if mode == 'MQTT' and loglevel == 'DEBUG' and action != 'Connect':
                
            log += '\n\n\tTopic: ' + data['topic'] + '\n\tPayload: ' + json.dumps(data['payload']) + '\n\n'
                   
        if logtype == 'ERROR':
            
            print (f'{Style.ERROR}' + log + f'{Style.RESET}')
            
        else:
            
            print (log)
            
            
async def publish_message(msg, qosValue, logOnly, retain=False):
    
    
    if not logOnly:
        outputDevices[0]['output']['0'].toggle()
        await client.publish(msg['topic'], json.dumps(msg['payload']).encode(), retain=retain, qos=qosValue)
        logOutput ('MQTT', 'Publish', msg, 'INFO')
        outputDevices[0]['output']['0'].toggle()


async def sync_ntp_time():
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
    if not ha_discovery:
        return

    device_info_added = False

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
            if device_char and 'driver' in device_char:
                try:
                    payload_discovery, payload_entities = device_char['driver'].get_discovery_payloads(deviceid, ha_devicename)
                except Exception:
                    payload_discovery = {}
                    payload_entities = {}

            if not device_info_added and payload_discovery:
                payload_discovery[0].update({
                    "dev": homeassistant_device_info(deviceid, ha_devicename)
                })
                device_info_added = True

            for i in payload_discovery:
                data = {
                    'payload': payload_discovery[i],
                    'topic': 'homeassistant/' + device['type']['class'] + '/' + deviceid + device['uuid'] + '_' + str(i) + '/config',
                    'log': 'HA Discovery: ' + device['name']
                }
                asyncio.create_task(publish_message(data, 0, False, True))

            await asyncio.sleep(1)

            data = {
                'payload': payload_entities,
                'topic': 'homeassistant/' + device['type']['class'] + '/' + deviceid + device['uuid'] + '/state',
                'log': 'HA Update: ' + device['name']
            }
            asyncio.create_task(publish_message(data, 0, False))
       
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
        'topic': 'homeassistant/' + devicetype + '/' + deviceid + uuid + '/state',
        'log': 'HA Update: ' + deviceObjects[device['index']]['name']
    }

    return data



async def messages(client):  # Respond to incoming messages
    async for topic, payload, retained in client.queue:
        msg_topic = topic.decode('utf-8')
        
        if msg_topic == 'homeassistant/status':
            
            msg_payload = payload.decode('utf-8')
            
            data = {
                'payload': msg_payload,
                'topic': msg_topic,
                'log': 'HA Status: ' + msg_payload
                }

            if msg_payload == 'online':

                asyncio.create_task(homeassistant_discovery())
            
            logOutput ('MQTT', 'Received', data, 'INFO')                
            
        else:
            
            msg_payload = json.loads(payload.decode('utf-8'))
 
            data = {
                    'payload': msg_payload,
                    'topic': msg_topic,
                    'log': msg_topic
                }
    
            logOutput ('MQTT', 'Received', data, 'INFO')
    
            msg_parts = msg_topic.split('/', 3)
            if len(msg_parts) != 4:
                continue

            msg_topic_1, msg_topic_2, msg_topic_3, msg_topic_4 = msg_parts

            if msg_topic_1 == 'homeassistant':
            
                data = device_config(msg_topic_2, msg_topic_3[len(deviceid):len(msg_topic_3)], msg_topic_4, msg_payload)
                if data:
                    asyncio.create_task(publish_message(data, 0, False))
                
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
            
                await client.subscribe('homeassistant/' + device['type']['class'] + '/' + deviceid + device['uuid'] + '/set', 1)
            
                logOutput ('MQTT', 'Subscribe', {'log':'Topic: homeassistant/' + device['type']['class'] + '/' + deviceid + device['uuid'] + '/set', 'topic': 'homeassistant/' + device['type']['class'] + '/' + deviceid + device['uuid'] + '/set', 'payload': None}, 'INFO')   
            
        asyncio.create_task(homeassistant_discovery())

        await asyncio.sleep(0)


def ssl_error_message(exc):
    detail = str(exc).strip()
    if not detail and getattr(exc, 'args', None):
        detail = ' '.join(str(arg) for arg in exc.args if arg)

    if not detail:
        detail = 'certificate validation failed'

    if 'validity has expired' in detail:
        detail += ' - renew the broker certificate or check the device clock/NTP.'

    if 'Common Name' in detail or 'expected CN' in detail:
        detail += ' - connect using the hostname covered by the certificate, or update the certificate SAN/CN.'

    return detail



async def main(client):
    try:
        await client.connect()
    except ValueError as exc:
        logOutput('MQTT', 'Connect', {'log': 'SSL error: ' + ssl_error_message(exc)}, 'ERROR')
        return
    except OSError as exc:
        logOutput('MQTT', 'Connect', {'log': 'Connection error: ' + str(exc)}, 'ERROR')
        return

    for coroutine in (up, messages):
        asyncio.create_task(coroutine(client))
    
    while True:
        await asyncio.sleep(5)
        # If WiFi is down the following will pause for the duration.
        outputDevices[0]['output']['0'](1)
        await asyncio.sleep(1)
        outputDevices[0]['output']['0'](0)


logOutput ('MQTT', 'Connect', {'log':'Load CA Trust Certificate'}, 'INFO')
    
with open(ca_cert_path, 'rb') as f:
    cacert = f.read()
        
logOutput ('MQTT', 'Connect', {'log':'Loaded CA Trust Certificate'}, 'INFO')

# Load device types from registered modules
deviceTypes = get_device_types()

config['client_id'] = deviceid
config['ssl_params'] = {'server_side':False, 'key':None, 'cert':None, 'cadata':cacert, 'cert_reqs':ssl.CERT_REQUIRED, 'server_hostname': config['server']}
config["queue_len"] = 1  # Use event interface with default queue size

MQTTClient.DEBUG = mqtt_debug

client = MQTTClient(config)

# Helper for drivers to publish via main publish_message
def publish_wrapper(data, qosValue, logOnly):
    try:
        asyncio.create_task(publish_message(data, qosValue, logOnly))
    except Exception:
        pass

# Import Device Configuration, Validate, Associate GPIO Inputs & Outputs and Initialise

i = 1

logOutput ('Local', 'Device', {'log':'Importing device configuration file: ' + deviceConfigFile}, 'INFO')

with open(deviceConfigFile, 'rb') as f:

    deviceConfig = json.loads(f.read())
    
logOutput ('Local', 'Device', {'log':'Imported device configuration file: ' + deviceConfigFile}, 'INFO')
        
for device in deviceConfig['devices']:
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
                device_char['driver'].start(publish_wrapper, deviceid)
            except Exception as exc:
                logOutput('Local', 'Start device', {'log': device['name'] + ' - ' + str(exc)}, 'ERROR')
                    

try:
    asyncio.run(main(client))
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
