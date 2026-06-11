from machine import Pin
from primitives import Pushbutton
try:
    from .base import DeviceDriver
except ImportError:
    from base import DeviceDriver


DEVICE_TYPE = {
    'class': 'switch',
    'subclass': {'onoff'},
    'ha_discovery': False,
    'ha_subscribe': False,
    'local_init': False
}


def supports(device):
    return (device['type']['class'] == 'switch' and 
            device['type']['subclass'] == 'onoff')


def setup(device, index):
    device_char = {'uuid': device['uuid'], 'index': index}
    
    if 'gpio' in device and 'input' in device['gpio']:
        device_char.update({
            'gpio': {0: device['gpio']['input']['0']},
            'input': {
                '0': Pushbutton(Pin(device['gpio']['input']['0'], Pin.IN, Pin.PULL_UP))
            }
        })
    
    return device_char


def create_driver(device, device_char):
    return SwitchOnoffDriver(device, device_char)


class SwitchOnoffDriver(DeviceDriver):
    def get_state_payload(self):
        return {}
