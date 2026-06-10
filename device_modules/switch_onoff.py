from machine import Pin
from primitives import Pushbutton
try:
    from .base import DeviceDriver
except ImportError:
    from base import DeviceDriver
import asyncio


def handle_local_input(inputDevice, deviceObjects, device_config, publish_message):
    """Handle local switch input (onoff and dimmer)."""
    
    logOnly = False
    inputdevice = next(device for device in deviceObjects if device['uuid'] == inputDevice[1])
    
    for i in inputdevice['output_uuid']:
        outputdevice = next(device for device in deviceObjects if device['uuid'] == inputdevice['output_uuid'][str(i)])
        
        if outputdevice['type']['class'] == 'light' and inputDevice[0] == 'onoff':
            if outputdevice['entities']['0']['state'] == 'ON':
                payload = {'state': 'OFF'}
            else:
                payload = {'state': 'ON'}
                
        if outputdevice['type']['class'] == 'light' and inputDevice[0] == 'dimmer':
            brightness = int(outputdevice['entities']['0']['brightness'] + 
                           inputDevice[2] * (255 * inputdevice['entities']['0']['step']/100))
            
            brightness = 0 if brightness < 0 else 255 if brightness > 255 else brightness
            
            if brightness == outputdevice['entities']['0']['brightness']:
                logOnly = True

            payload = {
                'state': 'ON',
                'brightness': brightness
            }
        
        data = device_config(outputdevice['type']['class'], outputdevice['uuid'], 'set', payload)
        asyncio.create_task(publish_message(data, 0, logOnly))


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
    def handle_set(self, payload):
        return

    def get_state_payload(self):
        return {}
