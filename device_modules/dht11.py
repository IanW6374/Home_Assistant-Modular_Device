from machine import Pin
from dht import DHT11
try:
    from .base import DeviceDriver
except ImportError:
    from base import DeviceDriver

DEVICE_TYPE = {
    'class': 'sensor',
    'subclass': {
        'dht11': {'entities': {'temperature', 'humidity'}}
    },
    'ha_discovery': True,
    'ha_subscribe': False,
    'local_init': False
}


def supports(device):
    return (device['type']['class'] == 'sensor' and 
            device['type']['subclass'] == 'dht11')


def setup(device, index):
    device_char = {'uuid': device['uuid'], 'index': index}
    
    if 'gpio' in device and 'input' in device['gpio']:
        device_char.update({
            'gpio': {0: device['gpio']['input']['0']},
            'input': {
                0: DHT11(Pin(device['gpio']['input']['0']))
            }
        })
    
    return device_char


def create_driver(device, device_char):
    return DHT11Driver(device, device_char)


class DHT11Driver(DeviceDriver):
    def get_discovery_payloads(self, deviceid, ha_devicename):
        payload_discovery = {}
        payload_entities = {}
        i = 0
        for e in self.device['entities']:
            payload_discovery[i] = {
                "~": "homeassistant/sensor/" + deviceid + self.device['uuid'],
                "stat_t": "~/state",
                "uniq_id": deviceid + self.device['uuid'] + '_' + str(i),
                "dev": self.discovery_device_info(deviceid, ha_devicename)
            }

            payload_discovery[i].update({
                "device_class": self.device['entities'][str(i)]['class'],
                "unit_of_measurement": self.device['entities'][str(i)]['unit'],
                "value_template": "{{value_json." + self.device['entities'][str(i)]['class'] + "}}"
            })

            payload_entities[self.device['entities'][str(i)]['class']] = self.device['entities'][str(i)]['value']
            i += 1

        return payload_discovery, payload_entities

    def get_state_payload(self):
        payload = {}
        for e in self.device['entities']:
            payload[self.device['entities'][str(e)]['class']] = self.device['entities'][str(e)]['value']
        return payload

    def start(self, publish_callable, deviceid, log_callable=None):
        import asyncio

        async def measure_loop():
            while True:
                try:
                    self.devchar['input'][0].measure()
                    temperature = self.devchar['input'][0].temperature()
                    humidity = self.devchar['input'][0].humidity()
                    for i in self.device['entities']:
                        if self.device['entities'][str(i)]['class'] == 'temperature':
                            self.device['entities'][str(i)]['value'] = temperature
                        if self.device['entities'][str(i)]['class'] == 'humidity':
                            self.device['entities'][str(i)]['value'] = humidity

                    self.publish_state(publish_callable, deviceid)
                except Exception:
                    pass

                interval = self.device.get('pollinterval', 60)
                await asyncio.sleep(interval)

        try:
            asyncio.create_task(measure_loop())
        except Exception:
            pass
