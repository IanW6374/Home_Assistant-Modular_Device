from machine import Pin, PWM
try:
    from .base import DeviceDriver
except ImportError:
    from base import DeviceDriver

PWM_MAX = 65535

DEVICE_TYPE = {
    'class': 'light',
    'subclass': {'onoff', 'brightness', 'rgb'},
    'ha_discovery': True,
    'ha_subscribe': True,
    'local_init': True
}


def supports(device):
    return device['type']['class'] == 'light'


def create_driver(device, device_char):
    return LightDriver(device, device_char)


def setup(device, index):
    device_char = {'uuid': device['uuid'], 'index': index}

    if 'gpio' in device and 'output' in device['gpio']:
        if device['type']['subclass'] == 'rgb':
            device_char.update({
                'output': {
                    'r': PWM(Pin(device['gpio']['output']['r'], Pin.OUT)),
                    'g': PWM(Pin(device['gpio']['output']['g'], Pin.OUT)),
                    'b': PWM(Pin(device['gpio']['output']['b'], Pin.OUT))
                }
            })
            # Set frequency after creating PWM instances
            for pin_name in ['r', 'g', 'b']:
                device_char['output'][pin_name].freq(device['gpio']['pwm_freq'])
        elif device['type']['subclass'] == 'brightness':
            device_char.update({
                'output': {
                    '0': PWM(Pin(device['gpio']['output']['0'], Pin.OUT))
                }
            })
            # Set frequency after creating PWM instance
            device_char['output']['0'].freq(device['gpio']['pwm_freq'])
        else:
            device_char.update({
                'output': {
                    '0': Pin(device['gpio']['output']['0'], Pin.OUT)
                }
            })

    return device_char


class LightDriver(DeviceDriver):
    def gpio_output(self, mode, state, brightness):
        brightness = int(brightness * PWM_MAX / 255)
        active_high = self.device['gpio']['activeHigh']

        if active_high and state == 'ON':
            dutycycle = brightness
            onoff = 1
        elif not active_high and state == 'ON':
            dutycycle = abs(brightness - PWM_MAX)
            onoff = 0
        elif active_high and state == 'OFF':
            dutycycle = 0
            onoff = 0
        else:
            dutycycle = PWM_MAX
            onoff = 1

        return dutycycle if mode in ('pwm', 'rgb') else onoff

    def get_discovery_payloads(self, deviceid, ha_devicename):
        payload_discovery = {}
        payload_entities = {}
        i = 0
        for e in self.device['entities']:
            payload_discovery[i] = {
                "~": "homeassistant/light/" + deviceid + self.device['uuid'],
                "stat_t": "~/state",
                "uniq_id": deviceid + self.device['uuid'] + '_' + str(i),
                "dev": self.discovery_device_info(deviceid, ha_devicename)
            }

            payload_discovery[i].update({
                "name": self.device['name'],
                "cmd_t": "~/set",
                "schema": "json",
            })

            if self.device['type']['subclass'] == 'brightness':
                payload_discovery[i].update({
                    "brightness": True,
                    "brightness_scale": 255,
                })

            if self.device['type']['subclass'] == 'rgb':
                payload_discovery[i].update({
                    "brightness": True,
                    "brightness_scale": 255,
                    "supported_color_modes": "rgb"
                })

            payload_entities = self.device['entities'][str(i)]
            i += 1

        return payload_discovery, payload_entities

    def set(self, payload):
        if self.device['type']['subclass'] == 'onoff':
            brightness = 0
            state = payload.get('state', self.device['entities']['0']['state'])
            self.devchar['output']['0'](self.gpio_output('onoff', state, brightness))
            self.device['entities']['0']['state'] = state

        elif self.device['type']['subclass'] == 'brightness':
            state = payload.get('state', self.device['entities']['0']['state'])
            brightness = payload.get('brightness', self.device['entities']['0'].get('brightness', 0))
            self.devchar['output']['0'].duty_u16(self.gpio_output('pwm', state, brightness))
            self.device['entities']['0']['state'] = state
            self.device['entities']['0']['brightness'] = brightness

        elif self.device['type']['subclass'] == 'rgb':
            if 'color' in payload:
                self.device['entities']['0']['color']['r'] = payload['color'].get('r', self.device['entities']['0']['color']['r'])
                self.device['entities']['0']['color']['g'] = payload['color'].get('g', self.device['entities']['0']['color']['g'])
                self.device['entities']['0']['color']['b'] = payload['color'].get('b', self.device['entities']['0']['color']['b'])

            brightness = payload.get('brightness', self.device['entities']['0'].get('brightness', 255))
            state = payload.get('state', self.device['entities']['0']['state'])
            self.device['entities']['0']['brightness'] = brightness
            self.device['entities']['0']['state'] = state

            r = self.gpio_output('rgb', state, self.device['entities']['0']['color']['r'] * brightness / 255)
            g = self.gpio_output('rgb', state, self.device['entities']['0']['color']['g'] * brightness / 255)
            b = self.gpio_output('rgb', state, self.device['entities']['0']['color']['b'] * brightness / 255)

            self.devchar['output']['r'].duty_u16(r)
            self.devchar['output']['g'].duty_u16(g)
            self.devchar['output']['b'].duty_u16(b)

    def get_state_payload(self):
        return self.device['entities']['0']
