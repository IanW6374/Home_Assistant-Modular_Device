try:
    import device_settings
except ImportError:
    device_settings = None


def homeassistant_device_info(deviceid, ha_devicename):
    info = {}
    if device_settings:
        info.update(getattr(device_settings, 'ha_device_info', {}))

    info["identifiers"] = [ha_devicename]
    info["name"] = ha_devicename
    info["sn"] = deviceid
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


def ha_safe_id(value):
    value = str(value)
    safe = ''
    for char in value:
        if char.isalnum():
            safe += char.lower()
        else:
            safe += '_'
    while '__' in safe:
        safe = safe.replace('__', '_')
    return safe.strip('_') or 'entity'


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
        "dev": homeassistant_device_info(deviceid, ha_devicename)
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

    return payload


class DeviceDriver:
    def __init__(self, device, device_char):
        self.device = device
        self.devchar = device_char

    def discovery_device_info(self, deviceid, ha_devicename):
        return homeassistant_device_info(deviceid, ha_devicename)

    def get_discovery_payloads(self, deviceid, ha_devicename):
        raise NotImplementedError

    def get_state_payload(self):
        raise NotImplementedError

    def publish_state(self, publish_callable, deviceid):
        payload = self.get_state_payload()
        data = {
            'payload': payload,
            'topic': ha_state_topic(self.device['type']['class'], deviceid, self.device['uuid']),
            'log': 'HA Update: ' + self.device['name']
        }
        publish_callable(data, 0, False)

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
        topics = []
        current_ids = set(str(entity_id) for entity_id in current_ids)
        cleanup_count = max(len(current_ids) + 10, 64)
        if device_settings:
            cleanup_count = getattr(
                device_settings,
                'ha_discovery_cleanup_legacy_count',
                cleanup_count
            )

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
