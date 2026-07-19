"""Single-port RS485 Modbus RTU sensor transport.

Provides the shared RS485 driver's polling, grouping, decoding, MQTT
request/response, and diagnostics behaviour with one explicitly configured
UART.  The port is always exposed as ``ch0`` for compatibility with WHES
entity configurations.
"""

try:
    from . import modbus_transport as modbus_transport
    from .logging import log_output
except ImportError:
    import modbus_transport as modbus_transport
    from logging import log_output

from machine import UART, Pin


DEVICE_TYPE = {
    'class': 'sensor',
    'subclass': {
        'RS485-Modbus': {
            'entities': {
                'battery',
                'energy',
                'memory_value',
                'power',
                'temperature',
                'voltage'
            }
        }
    },
    'ha_discovery': True,
    'ha_subscribe': True,
    'local_init': False
}


PORT_NAME = 'ch0'
DEFAULT_TIMEOUT_MS = 500


def supports(device):
    return (
        device['type']['class'] == 'sensor' and
        device['type']['subclass'] == 'RS485-Modbus'
    )


def _as_pin(value):
    if value is None:
        return None
    return Pin(value)


def _port_config(device):
    rs485 = device.get('rs485', {})
    ports = rs485.get('ports')
    if ports:
        if len(ports) != 1:
            raise ValueError('single-port RS485 requires exactly one configured port')
        for config in ports.values():
            return config, rs485
    return rs485, rs485


def setup(device, index):
    device_char = {'uuid': device['uuid'], 'index': index, 'ports': {}}
    try:
        config, rs485 = _port_config(device)
        uart = UART(
            config.get('uart', 1),
            baudrate=config.get('baudrate', 9600),
            bits=config.get('bits', 8),
            parity=config.get('parity', None),
            stop=config.get('stop', 1),
            tx=_as_pin(config.get('tx', 17)),
            rx=_as_pin(config.get('rx', 18))
        )

        tx_enable = None
        if config.get('de') is not None:
            tx_enable = Pin(config['de'], Pin.OUT)
            tx_enable.value(0 if config.get('tx_enable_active', 1) else 1)

        device_char['ports'][PORT_NAME] = {
            'uart': uart,
            'tx_enable': tx_enable,
            'tx_enable_active': config.get('tx_enable_active', 1),
            'turnaround_ms': config.get('turnaround_ms', 5),
            'timeout_ms': config.get(
                'timeout_ms', rs485.get('timeout_ms', DEFAULT_TIMEOUT_MS)
            )
        }
    except Exception as exc:
        log_output(
            'Local', 'RS485-Modbus',
            {'log': 'Setup port error ' + str(exc)}, 'ERROR'
        )

    return device_char


def create_driver(device, device_char):
    return RS485ModbusDriver(device, device_char)


class RS485ModbusDriver(modbus_transport.ModbusRTUDriver):
    """Single-port driver retaining the transport API consumed by WHES."""

    def _log(self, message, logtype='INFO'):
        if self._log_callable:
            self._log_callable('Local', 'RS485-Modbus', {'log': message}, logtype)
        else:
            log_output('Local', 'RS485-Modbus', {'log': message}, logtype)
