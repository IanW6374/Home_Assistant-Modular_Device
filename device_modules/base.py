import settings_loader as device_settings

try:
    import time
except ImportError:
    time = None


def homeassistant_device_info(deviceid, ha_devicename, configuration_url=None):
    info = {}
    info.update(device_settings.ha_device_info)

    info["ids"] = [deviceid]
    info["name"] = ha_devicename
    info["sn"] = deviceid
    if configuration_url:
        info["cu"] = configuration_url
    return info


def homeassistant_origin_info():
    info = {
        "name": "Home Assistant Modular Device"
    }
    device_info = device_settings.ha_device_info
    software = device_info.get('sw') or device_info.get('sw_version')
    if software:
        info["sw"] = software
    return info


def ha_device_topic(device_type, deviceid, uuid):
    return 'homeassistant/' + device_type + '/' + deviceid + uuid


def ha_state_topic(device_type, deviceid, uuid):
    return ha_device_topic(device_type, deviceid, uuid) + '/state'


def ha_config_topic(device_type, deviceid, uuid, entity_id):
    return ha_device_topic(device_type, deviceid, uuid) + '_' + str(entity_id) + '/config'


def ha_set_topic(device_type, deviceid, uuid):
    return ha_device_topic(device_type, deviceid, uuid) + '/set'


def ha_response_topic(device_type, deviceid, uuid):
    return ha_device_topic(device_type, deviceid, uuid) + '/response'


def ha_availability_topic(deviceid):
    return 'homeassistant/status/' + deviceid + '/availability'


def ha_safe_id(value):
    value = str(value)
    safe = ''
    for char in value:
        if _is_ascii_alnum(char):
            safe += char.lower()
        else:
            safe += '_'
    while '__' in safe:
        safe = safe.replace('__', '_')
    return safe.strip('_') or 'entity'


def _is_ascii_alnum(char):
    return (
        ('0' <= char <= '9') or
        ('A' <= char <= 'Z') or
        ('a' <= char <= 'z')
    )


def ha_unique_id(deviceid, uuid, entity_id):
    return deviceid + uuid + '_' + ha_safe_id(entity_id)


def sensor_discovery_payload(device, entity, key, index, deviceid, ha_devicename):
    entity_id = entity.get('ha_id', key)
    payload = {
        "~": ha_device_topic(device['type']['class'], deviceid, device['uuid']),
        "stat_t": "~/state",
        "uniq_id": ha_unique_id(deviceid, device['uuid'], entity_id),
        "name": device['name'] + ' ' + key,
        "value_template": "{{ value_json[" + repr(key) + "] }}",
        "availability_topic": ha_availability_topic(deviceid),
        "payload_available": "online",
        "payload_not_available": "offline",
        "dev": homeassistant_device_info(deviceid, ha_devicename, device.get('_portal_url')),
        "o": homeassistant_origin_info()
    }

    entity_class = entity.get('class')
    if entity_class and entity_class != 'memory_value':
        payload['device_class'] = entity_class
    if entity.get('unit', ''):
        payload['unit_of_measurement'] = entity['unit']
    if 'state_class' in entity:
        payload['state_class'] = entity['state_class']
    if 'entity_category' in entity:
        payload['entity_category'] = entity['entity_category']
    if entity.get('entity_category') == 'diagnostic':
        payload['en'] = False

    return payload


class DeviceDriver:
    def __init__(self, device, device_char):
        self.device = device
        self.devchar = device_char
        self.health = {
            'last_ok': False,
            'last_error': '',
            'last_read_ms': None,
            'last_publish_ms': None,
            'consecutive_errors': 0
        }

    def discovery_device_info(self, deviceid, ha_devicename):
        return homeassistant_device_info(deviceid, ha_devicename, self.device.get('_portal_url'))

    def get_discovery_payloads(self, deviceid, ha_devicename):
        raise NotImplementedError

    def get_state_payload(self):
        raise NotImplementedError

    def publish_state(self, publish_callable, deviceid):
        payload = self.get_state_payload()
        self.mark_publish()
        payload.update(self.health_state_payload())
        data = {
            'payload': payload,
            'topic': ha_state_topic(self.device['type']['class'], deviceid, self.device['uuid']),
            'log': 'HA Update: ' + self.device['name']
        }
        retain = bool(self.device.get('retain_state', False))
        publish_callable(data, 0, False, retain)

    def publish_discovery(self, publish_callable, deviceid, ha_devicename=None):
        payloads, _ = self.get_discovery_payloads(deviceid, ha_devicename or self.device.get('name', ''))
        for i in payloads:
            data = {
                'payload': payloads[i],
                'topic': ha_config_topic(self.device['type']['class'], deviceid, self.device['uuid'], i),
                'log': 'HA Discovery: ' + self.device['name']
            }
            publish_callable(data, 0, False)

    def discovery_cleanup_topics(self, deviceid, current_ids):
        if not device_settings.ha_discovery_cleanup_legacy:
            return []

        topics = []
        current_ids = set(str(entity_id) for entity_id in current_ids)
        cleanup_count = max(len(current_ids) + 10, 64)
        cleanup_count = device_settings.ha_discovery_cleanup_legacy_count

        for index in range(cleanup_count):
            entity_id = str(index)
            if entity_id not in current_ids:
                topics.append(ha_config_topic(
                    self.device['type']['class'],
                    deviceid,
                    self.device['uuid'],
                    entity_id
                ))

        return topics

    def handle_set(self, payload):
        return

    def set(self, payload):
        return

    def start(self, publish_callable, deviceid, log_callable=None):
        return

    def mark_read_ok(self, elapsed_ms=None):
        self.health['last_ok'] = True
        self.health['last_error'] = ''
        self.health['last_read_ms'] = elapsed_ms
        self.health['consecutive_errors'] = 0

    def mark_read_error(self, error):
        self.health['last_ok'] = False
        self.health['last_error'] = str(error)
        self.health['consecutive_errors'] = int(self.health.get('consecutive_errors') or 0) + 1

    def mark_publish(self):
        self.health['last_publish_ms'] = _ticks_ms()

    def diagnostics_payload(self):
        payload = self.health.copy()
        payload['last_publish_age_s'] = self.last_publish_age_s()
        return payload

    def health_state_payload(self):
        payload = {}
        for key in ('last_ok', 'last_error', 'last_read_ms', 'consecutive_errors'):
            payload['module_' + key] = self.health.get(key)
        payload['module_last_publish_age_s'] = self.last_publish_age_s()
        return payload

    def set_calibration(self, payload):
        return False

    def last_publish_age_s(self):
        last_publish_ms = self.health.get('last_publish_ms')
        if last_publish_ms is None:
            return None
        return int(max(0, _ticks_diff(_ticks_ms(), last_publish_ms) / 1000))


def _ticks_ms():
    if time and hasattr(time, 'ticks_ms'):
        return time.ticks_ms()
    if time:
        return int(time.time() * 1000)
    return 0


def _ticks_diff(end, start):
    if time and hasattr(time, 'ticks_diff'):
        return time.ticks_diff(end, start)
    return end - start


def handle_local_input(input_device, device_objects, device_config, publish_message):
    import asyncio

    inputdevice = next(device for device in device_objects if device['uuid'] == input_device[1])

    for i in inputdevice['output_uuid']:
        outputdevice = next(device for device in device_objects if device['uuid'] == inputdevice['output_uuid'][str(i)])
        payload = None
        log_only = False

        if outputdevice['type']['class'] == 'light' and input_device[0] == 'onoff':
            payload = {
                'state': 'OFF' if outputdevice['entities']['0']['state'] == 'ON' else 'ON'
            }

        elif outputdevice['type']['class'] == 'light' and input_device[0] == 'dimmer':
            brightness = int(outputdevice['entities']['0']['brightness'] +
                             input_device[2] * (255 * inputdevice['entities']['0']['step'] / 100))
            brightness = max(0, min(255, brightness))
            log_only = brightness == outputdevice['entities']['0']['brightness']
            payload = {
                'state': 'ON',
                'brightness': brightness
            }

        if payload is None:
            continue

        data = device_config(outputdevice['type']['class'], outputdevice['uuid'], 'set', payload)
        asyncio.create_task(publish_message(data, 0, log_only))
