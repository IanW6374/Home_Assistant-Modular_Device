"""Legacy Pico-2CH-RS485 configuration compatibility shim.

New ESP32-S3 configurations should use ``RS485-Modbus`` or
``RS485-Modbus-Multiport``. This module preserves existing settings while the
generic transport no longer carries a platform-specific filename.
"""

try:
    from . import modbus_transport as _transport
    from .modbus_transport import ModbusRTUDriver
except ImportError:
    import modbus_transport as _transport
    from modbus_transport import ModbusRTUDriver

time = _transport.time


DEVICE_TYPE = {
    'class': 'sensor',
    'subclass': {
        'Pico-2CH-RS485': {
            'entities': {'battery', 'memory_value', 'power', 'energy'}
        }
    },
    'ha_discovery': True,
    'ha_subscribe': True,
    'local_init': False
}


Pico2CHRS485Driver = ModbusRTUDriver


def supports(device):
    return (
        device['type']['class'] == 'sensor' and
        device['type']['subclass'] == 'Pico-2CH-RS485'
    )


def setup(device, index):
    # Import lazily to keep the compatibility shim small.
    try:
        from .modbus_transport import setup as generic_setup
    except ImportError:
        from modbus_transport import setup as generic_setup
    compatible = dict(device)
    compatible['type'] = dict(device.get('type', {}))
    compatible['type']['subclass'] = 'RS485-Modbus-Multiport'
    return generic_setup(compatible, index)


def create_driver(device, device_char):
    return ModbusRTUDriver(device, device_char)
