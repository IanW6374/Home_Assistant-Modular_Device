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


def ha_config_topic(device_type, deviceid, uuid, index):
    return ha_device_topic(device_type, deviceid, uuid) + '_' + str(index) + '/config'


def ha_set_topic(device_type, deviceid, uuid):
    return ha_device_topic(device_type, deviceid, uuid) + '/set'


def ha_response_topic(device_type, deviceid, uuid):
    return ha_device_topic(device_type, deviceid, uuid) + '/response'


def sensor_discovery_payload(device, entity, key, index, deviceid, ha_devicename):
    payload = {
        "~": ha_device_topic(device['type']['class'], deviceid, device['uuid']),
        "stat_t": "~/state",
        "uniq_id": deviceid + device['uuid'] + '_' + str(index),
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

    def handle_set(self, payload):
        return

    def set(self, payload):
        return

    def start(self, publish_callable, deviceid):
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
