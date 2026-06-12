"""Pico 2-channel RS485 sensor module.

Polls multiple Modbus RTU memory/register addresses over one or more Pico UARTs
and publishes readings to MQTT. Also accepts ad-hoc read requests via the
device's MQTT ``/set`` topic and publishes replies to ``/response``.
"""

try:
    from ustruct import unpack
except ImportError:
    from struct import unpack

from machine import UART, Pin
try:
    from .base import DeviceDriver
except ImportError:
    from base import DeviceDriver
import asyncio
import time


DEVICE_TYPE = {
    'class': 'sensor',
    'subclass': {
        'Pico-2CH-RS485': {
            'entities': {
                'battery',
                'memory_value',
                'power',
                'energy'
            }
        }
    },
    'ha_discovery': True,
    'ha_subscribe': True,
    'local_init': False
}


DEFAULT_PORT = 'ch0'
DEFAULT_TIMEOUT_MS = 500
DEFAULT_POLL_INTERVAL = 60


def _timestamp():
    current_time = time.localtime()
    return "{:04}{:02}{:02} {:02}{:02}{:02}".format(
        current_time[0],
        current_time[1],
        current_time[2],
        current_time[3],
        current_time[4],
        current_time[5]
    )


def supports(device):
    return (
        device['type']['class'] == 'sensor' and
        device['type']['subclass'] == 'Pico-2CH-RS485'
    )


def _as_pin(value):
    if value is None:
        return None
    return Pin(value)


def setup(device, index):
    device_char = {'uuid': device['uuid'], 'index': index, 'ports': {}}
    rs485 = device.get('rs485', {})
    ports = rs485.get('ports')

    if not ports:
        ports = {
            DEFAULT_PORT: {
                'uart': device.get('uart', 1),
                'tx': device.get('tx', 8),
                'rx': device.get('rx', 9),
                'baudrate': device.get('baudrate', 9600)
            }
        }

    for name in ports:
        cfg = ports[name]
        try:
            uart = UART(
                cfg.get('uart', 1),
                baudrate=cfg.get('baudrate', 9600),
                bits=cfg.get('bits', 8),
                parity=cfg.get('parity', None),
                stop=cfg.get('stop', 1),
                tx=_as_pin(cfg.get('tx')),
                rx=_as_pin(cfg.get('rx'))
            )

            tx_enable = None
            if 'de' in cfg:
                tx_enable = Pin(cfg['de'], Pin.OUT)
                tx_enable.value(0 if cfg.get('tx_enable_active', 1) else 1)

            device_char['ports'][name] = {
                'uart': uart,
                'tx_enable': tx_enable,
                'tx_enable_active': cfg.get('tx_enable_active', 1),
                'turnaround_ms': cfg.get('turnaround_ms', 5),
                'timeout_ms': cfg.get('timeout_ms', rs485.get('timeout_ms', DEFAULT_TIMEOUT_MS))
            }
        except Exception as exc:
            print('Pico-2CH-RS485.setup port error', name, exc)

    return device_char


def create_driver(device, device_char):
    return Pico2CHRS485Driver(device, device_char)


class Pico2CHRS485Driver(DeviceDriver):
    def __init__(self, device, device_char):
        super().__init__(device, device_char)
        self._publish_callable = None
        self._deviceid = None
        self._pending = []
        self._running = False
        self._bus_busy = False

    def get_discovery_payloads(self, deviceid, ha_devicename):
        payload_discovery = {}
        payload_entities = {}
        i = 0

        for e in self.device['entities']:
            entity = self.device['entities'][str(e)]
            key = entity.get('key', entity['class'])

            payload_discovery[i] = {
                "~": "homeassistant/sensor/" + deviceid + self.device['uuid'],
                "stat_t": "~/state",
                "uniq_id": deviceid + self.device['uuid'] + '_' + str(i),
                "name": self.device['name'] + ' ' + key,
                "value_template": "{{ value_json[" + repr(key) + "] }}",
                "dev": self.discovery_device_info(deviceid, ha_devicename)
            }

            if entity['class'] != 'memory_value':
                payload_discovery[i]['device_class'] = entity['class']
            if entity.get('unit', ''):
                payload_discovery[i]['unit_of_measurement'] = entity['unit']
            if 'state_class' in entity:
                payload_discovery[i]['state_class'] = entity['state_class']
            if 'entity_category' in entity:
                payload_discovery[i]['entity_category'] = entity['entity_category']

            payload_entities[key] = entity.get('value', 0)
            i += 1

        return payload_discovery, payload_entities

    def get_state_payload(self):
        payload = {}
        for e in self.device['entities']:
            entity = self.device['entities'][str(e)]
            payload[entity.get('key', entity['class'])] = entity.get('value', 0)
        return payload

    def set(self, payload):
        """Queue an ad-hoc read request from MQTT.

        Payload example:
        {
            "request_id": "optional-correlation-id",
            "port": "ch0",
            "slave": 1,
            "address": 3000,
            "count": 2,
            "function": 4,
            "data_type": "uint32",
            "scale": 0.1
        }
        """
        if self._publish_callable and self._deviceid:
            asyncio.create_task(self._read_and_publish(payload))
        else:
            self._pending.append(payload)
        return {'defer_publish': True}

    def start(self, publish_callable, deviceid):
        self._publish_callable = publish_callable
        self._deviceid = deviceid

        if self._running:
            return
        self._running = True
        entities = self._poll_entities()

        async def poll_loop():
            first_poll = True

            while True:
                try:
                    await self._handle_pending()
                    changed = False
                    now = time.ticks_ms()
                    next_delay = None

                    for entity in entities:
                        pollinterval = self._entity_pollinterval(entity)
                        due = first_poll or (
                            pollinterval > 0 and
                            time.ticks_diff(now, entity.get('_next_poll', 0)) >= 0
                        )

                        if due:
                            value = await self._read_entity(entity)
                            if value is not None:
                                entity['value'] = value
                                changed = True

                            if pollinterval > 0:
                                entity['_next_poll'] = time.ticks_add(time.ticks_ms(), int(pollinterval * 1000))

                        if pollinterval > 0:
                            delay = max(0, time.ticks_diff(entity.get('_next_poll', now), time.ticks_ms()))
                            if next_delay is None or delay < next_delay:
                                next_delay = delay

                    if changed:
                        self.publish_state(publish_callable, deviceid)

                    await self._handle_pending()
                except Exception as exc:
                    print('Pico-2CH-RS485 poll error', exc)

                first_poll = False
                await asyncio.sleep_ms(next_delay if next_delay is not None else 1000)

        try:
            asyncio.create_task(poll_loop())
        except Exception as exc:
            print('Pico-2CH-RS485.start error', exc)

    async def _handle_pending(self):
        while self._pending:
            request = self._pending.pop(0)
            await self._read_and_publish(request)
            await asyncio.sleep(0)

    def _poll_entities(self):
        entities = []
        for e in self.device['entities']:
            entity = self.device['entities'][str(e)]
            if entity.get('poll', True):
                entity['_next_poll'] = time.ticks_ms()
                entities.append(entity)
        return entities

    def _entity_pollinterval(self, entity):
        return entity.get('pollinterval', self.device.get('pollinterval', DEFAULT_POLL_INTERVAL))

    async def _read_and_publish(self, request):
        response = await self._read_request(request)
        self._publish_response(response)

    async def _read_entity(self, entity):
        key = entity.get('key', entity['class'])
        request = {
            'port': entity.get('port', DEFAULT_PORT),
            'slave': entity.get('slave', self.device.get('slave', 1)),
            'address': entity.get('address', entity.get('memory_address')),
            'count': entity.get('count', 1),
            'function': entity.get('function', entity.get('function_code', 3)),
            'data_type': entity.get('data_type', entity.get('type', 'uint16')),
            'scale': entity.get('scale', 1),
            'offset': entity.get('offset', 0),
            'byte_order': entity.get('byte_order', 'big'),
            'word_order': entity.get('word_order', 'big')
        }
        response = await self._read_request(request)
        if response.get('ok'):
            return response['value']
        print(_timestamp(), ' Local: Pico-2CH-RS485 - Read failed',
              key, 'port', request['port'], 'slave', request['slave'],
              'address', request['address'], response.get('error'))
        if response.get('error') == 'timeout':
            return 0
        return None

    async def _read_request(self, request):
        response = {
            'ok': False,
            'request_id': request.get('request_id'),
            'port': request.get('port', DEFAULT_PORT),
            'slave': request.get('slave', self.device.get('slave', 1)),
            'address': request.get('address', request.get('memory_address')),
            'count': request.get('count', 1),
            'function': request.get('function', request.get('function_code', 3))
        }

        try:
            if response['address'] is None:
                raise ValueError('missing address')

            await self._acquire_bus()
            try:
                raw = await self._modbus_read(
                    response['port'],
                    int(response['slave']),
                    int(response['function']),
                    int(response['address']),
                    int(response['count'])
                )
            finally:
                self._release_bus()

            value = self._decode_registers(
                raw,
                request.get('data_type', request.get('type', 'uint16')),
                request.get('byte_order', 'big'),
                request.get('word_order', 'big')
            )
            if not isinstance(value, str):
                value = (value * request.get('scale', 1)) + request.get('offset', 0)

            response.update({
                'ok': True,
                'value': value,
                'raw': self._hex(raw)
            })
        except Exception as exc:
            error = str(exc)
            response['error'] = error
            if error == 'timeout':
                response['value'] = 0
                response['raw'] = ''

        return response

    async def _acquire_bus(self):
        while self._bus_busy:
            await asyncio.sleep_ms(10)
        self._bus_busy = True

    def _release_bus(self):
        self._bus_busy = False

    async def _modbus_read(self, port_name, slave, function, address, count):
        port = self.devchar['ports'].get(port_name)
        if not port:
            raise ValueError('unknown port ' + str(port_name))

        uart = port['uart']
        request = bytes([
            slave & 0xff,
            function & 0xff,
            (address >> 8) & 0xff,
            address & 0xff,
            (count >> 8) & 0xff,
            count & 0xff
        ])
        request += self._crc_bytes(request)

        self._drain(uart)
        self._set_tx(port, True)
        uart.write(request)
        if hasattr(uart, 'flush'):
            uart.flush()
        await asyncio.sleep_ms(port.get('turnaround_ms', 5))
        self._set_tx(port, False)

        expected = 5 + (count * 2)
        reply = await self._read_exact(uart, expected, port.get('timeout_ms', DEFAULT_TIMEOUT_MS))
        if len(reply) < 5:
            raise ValueError('timeout')
        if self._crc(reply[:-2]) != (reply[-2] | (reply[-1] << 8)):
            raise ValueError('crc mismatch')
        if reply[0] != slave:
            raise ValueError('unexpected slave')
        if reply[1] == (function | 0x80):
            raise ValueError('modbus exception ' + str(reply[2]))
        if reply[1] != function:
            raise ValueError('unexpected function')
        if reply[2] != count * 2:
            raise ValueError('unexpected byte count')

        return reply[3:3 + reply[2]]

    async def _read_exact(self, uart, size, timeout_ms):
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        data = b''

        while len(data) < size and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if uart.any():
                chunk = uart.read(size - len(data))
                if chunk:
                    data += chunk
            else:
                await asyncio.sleep_ms(5)

        return data

    def _set_tx(self, port, enabled):
        pin = port.get('tx_enable')
        if pin:
            active = port.get('tx_enable_active', 1)
            pin.value(active if enabled else 1 - active)

    def _drain(self, uart):
        while uart.any():
            uart.read()

    def _publish_response(self, payload):
        if not self._publish_callable or not self._deviceid:
            return

        data = {
            'payload': payload,
            'topic': 'homeassistant/sensor/' + self._deviceid + self.device['uuid'] + '/response',
            'log': 'RS485 response: ' + self.device['name']
        }
        self._publish_callable(data, 0, False)

    def _decode_registers(self, raw, data_type, byte_order, word_order):
        if data_type == 'ascii':
            return ''.join(chr(byte) for byte in raw if 32 <= byte <= 126).rstrip()

        if byte_order == 'little':
            words = []
            for i in range(0, len(raw), 2):
                words.append(bytes([raw[i + 1], raw[i]]))
            raw = b''.join(words)

        if len(raw) == 4 and word_order == 'little':
            raw = raw[2:4] + raw[0:2]

        if data_type == 'int16':
            value = (raw[0] << 8) | raw[1]
            return value - 65536 if value & 0x8000 else value
        if data_type == 'uint32':
            return (raw[0] << 24) | (raw[1] << 16) | (raw[2] << 8) | raw[3]
        if data_type == 'int32':
            value = (raw[0] << 24) | (raw[1] << 16) | (raw[2] << 8) | raw[3]
            return value - 4294967296 if value & 0x80000000 else value
        if data_type == 'float32':
            return unpack('>f', raw)[0]

        return (raw[0] << 8) | raw[1]

    def _crc_bytes(self, payload):
        crc = self._crc(payload)
        return bytes([crc & 0xff, (crc >> 8) & 0xff])

    def _crc(self, payload):
        crc = 0xffff
        for byte in payload:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xa001
                else:
                    crc >>= 1
        return crc

    def _hex(self, payload):
        chars = '0123456789abcdef'
        out = ''
        for byte in payload:
            out += chars[(byte >> 4) & 0x0f] + chars[byte & 0x0f]
        return out
