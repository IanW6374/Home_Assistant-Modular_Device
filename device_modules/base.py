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
            'topic': 'homeassistant/' + self.device['type']['class'] + '/' + deviceid + self.device['uuid'] + '/state',
            'log': 'HA Update: ' + self.device['name']
        }
        publish_callable(data, 0, False)

    def publish_discovery(self, publish_callable, deviceid, ha_devicename=None):
        payloads, _ = self.get_discovery_payloads(deviceid, ha_devicename or self.device.get('name', ''))
        for i in payloads:
            data = {
                'payload': payloads[i],
                'topic': 'homeassistant/' + self.device['type']['class'] + '/' + deviceid + self.device['uuid'] + '_' + str(i) + '/config',
                'log': 'HA Discovery: ' + self.device['name']
            }
            publish_callable(data, 0, False)

    def handle_set(self, payload):
        return

    def set(self, payload):
        return

    def start(self, publish_callable, deviceid):
        return
