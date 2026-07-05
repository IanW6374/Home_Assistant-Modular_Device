"""Pico 2-channel RS485 sensor module.

Polls multiple Modbus RTU memory/register addresses over one or more Pico UARTs
and publishes readings to MQTT. Also accepts ad-hoc read/write requests via the
device's MQTT ``/set`` topic and publishes replies to ``/response``.
"""

try:
    from ustruct import unpack
except ImportError:
    from struct import unpack

from machine import UART, Pin
try:
    from .base import DeviceDriver
    from .base import ha_safe_id
    from .base import ha_response_topic
    from .base import sensor_discovery_payload
    from .logging import log_output
except ImportError:
    from base import DeviceDriver
    from base import ha_safe_id
    from base import ha_response_topic
    from base import sensor_discovery_payload
    from logging import log_output
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
DEFAULT_MAX_GROUP_REGISTERS = 32


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
            log_output(
                'Local',
                'Pico-2CH-RS485',
                {'log': 'Setup port error ' + str(name) + ' ' + str(exc)},
                'ERROR'
            )

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
        self._log_callable = None
        self._last_request = {
            'ok': None,
            'operation': '',
            'address': '',
            'error': '',
            'latency_ms': 0
        }

    def get_discovery_payloads(self, deviceid, ha_devicename):
        payload_discovery = {}
        payload_entities = {}
        i = 0

        for e in self.device['entities']:
            entity = self.device['entities'][str(e)]
            key = entity.get('key', entity['class'])

            discovery_id = ha_safe_id(key)
            entity = entity.copy()
            entity['ha_id'] = key

            payload_discovery[discovery_id] = sensor_discovery_payload(
                self.device,
                entity,
                key,
                i,
                deviceid,
                ha_devicename
            )
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
        """Queue an ad-hoc read/write request from MQTT.

        Read payload example:
        {
            "request_id": "optional-correlation-id",
            "operation": "read",
            "port": "ch0",
            "slave": 1,
            "address": 36155,
            "count": 1,
            "function": 4,
            "data_type": "uint16",
            "scale": 0.1
        }

        Write payload example:
        {
            "request_id": "optional-correlation-id",
            "operation": "write",
            "port": "ch0",
            "slave": 1,
            "address": 60009,
            "value": 20,
            "data_type": "uint16",
            "scale": 0.01
        }
        """
        if self._publish_callable and self._deviceid:
            asyncio.create_task(self._request_and_publish(payload))
        else:
            self._pending.append(payload)
        return {'defer_publish': True}

    def start(self, publish_callable, deviceid, log_callable=None):
        self._publish_callable = publish_callable
        self._deviceid = deviceid
        self._log_callable = log_callable

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

                    due_entities = []

                    for entity in entities:
                        pollinterval = self._entity_pollinterval(entity)
                        due = first_poll or (
                            pollinterval > 0 and
                            time.ticks_diff(now, entity.get('_next_poll', 0)) >= 0
                        )

                        if due:
                            due_entities.append(entity)

                            if pollinterval > 0:
                                entity['_next_poll'] = time.ticks_add(time.ticks_ms(), int(pollinterval * 1000))

                    for group in self._poll_groups(due_entities):
                        results = await self._read_entity_group(group)
                        for entity, value in results:
                            if value is not None:
                                entity['value'] = value
                                changed = True

                    for entity in entities:
                        pollinterval = self._entity_pollinterval(entity)
                        if pollinterval > 0:
                            delay = max(0, time.ticks_diff(entity.get('_next_poll', now), time.ticks_ms()))
                            if next_delay is None or delay < next_delay:
                                next_delay = delay

                    if changed:
                        self.publish_state(publish_callable, deviceid)

                    await self._handle_pending()
                except Exception as exc:
                    self._log('Poll error ' + str(exc), 'ERROR')

                first_poll = False
                await asyncio.sleep_ms(next_delay if next_delay is not None else 1000)

        try:
            asyncio.create_task(poll_loop())
        except Exception as exc:
            self._log('Start error ' + str(exc), 'ERROR')

    def _log(self, message, logtype='INFO'):
        if self._log_callable:
            self._log_callable('Local', 'Pico-2CH-RS485', {'log': message}, logtype)
        else:
            log_output('Local', 'Pico-2CH-RS485', {'log': message}, logtype)

    async def _handle_pending(self):
        while self._pending:
            request = self._pending.pop(0)
            await self._request_and_publish(request)
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
        await self._request_and_publish(request)

    async def _request_and_publish(self, request):
        if self._is_write_request(request):
            response = await self._write_request(request)
        else:
            response = await self._read_request(request)
        self._publish_response(response)

    async def _read_entity(self, entity):
        key = entity.get('key', entity['class'])
        request = self._entity_request(entity)
        response = await self._read_request(request)
        if response.get('ok'):
            return response['value']
        self._log(
            'Read failed ' + str(key) +
            ' port ' + str(request['port']) +
            ' slave ' + str(request['slave']) +
            ' address ' + str(request['address']) +
            ' ' + str(response.get('error')),
            'ERROR'
        )
        if response.get('error') == 'timeout':
            return 0
        return None

    async def _read_entity_group(self, entities):
        if len(entities) == 1:
            value = await self._read_entity(entities[0])
            return [(entities[0], value)]

        first = self._entity_request(entities[0])
        start_address = self._as_int(first['address'])
        end_address = start_address
        keys = []

        for entity in entities:
            request = self._entity_request(entity)
            address = self._as_int(request['address'])
            count = self._as_int(request['count'])
            end_address = max(end_address, address + count)
            keys.append(entity.get('key', entity['class']))

        response = {
            'ok': False,
            'operation': 'read',
            'request_id': None,
            'port': first['port'],
            'slave': first['slave'],
            'address': start_address,
            'count': end_address - start_address,
            'function': first['function']
        }
        start_ms = self._ticks_ms()

        try:
            await self._acquire_bus()
            try:
                raw = await self._modbus_read(
                    response['port'],
                    self._as_int(response['slave']),
                    self._as_int(response['function']),
                    response['address'],
                    response['count']
                )
            finally:
                self._release_bus()

            results = []
            for entity in entities:
                request = self._entity_request(entity)
                offset = (self._as_int(request['address']) - start_address) * 2
                size = self._as_int(request['count']) * 2
                value = self._decode_entity_value(raw[offset:offset + size], request)
                results.append((entity, value))

            response.update({'ok': True, 'raw': self._hex(raw)})
            return results
        except Exception as exc:
            error = str(exc)
            response['error'] = error
            self._log(
                'Read failed group ' + ','.join(str(key) for key in keys) +
                ' port ' + str(response['port']) +
                ' slave ' + str(response['slave']) +
                ' address ' + str(response['address']) +
                ' count ' + str(response['count']) +
                ' ' + error,
                'ERROR'
            )
            if error == 'timeout':
                return [(entity, 0) for entity in entities]
            return [(entity, None) for entity in entities]
        finally:
            self._record_request_result(response, start_ms)

    async def _read_request(self, request):
        response = {
            'ok': False,
            'operation': 'read',
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

            start_ms = self._ticks_ms()
            await self._acquire_bus()
            try:
                raw = await self._modbus_read(
                    response['port'],
                    self._as_int(response['slave']),
                    self._as_int(response['function']),
                    self._as_int(response['address']),
                    self._as_int(response['count'])
                )
            finally:
                self._release_bus()

            value = self._decode_entity_value(raw, request)

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
        finally:
            self._record_request_result(response, start_ms if 'start_ms' in locals() else None)

        return response

    async def _write_request(self, request):
        response = {
            'ok': False,
            'operation': 'write',
            'request_id': request.get('request_id'),
            'port': request.get('port', DEFAULT_PORT),
            'slave': request.get('slave', self.device.get('slave', 1)),
            'address': request.get('address', request.get('memory_address')),
            'function': request.get('function', request.get('function_code'))
        }

        try:
            if response['address'] is None:
                raise ValueError('missing address')
            if 'value' not in request and 'values' not in request:
                raise ValueError('missing value')

            values = request.get('values')
            if values is None:
                values = [request.get('value')]
            elif not isinstance(values, (list, tuple)):
                values = [values]

            raw = self._encode_registers(
                values,
                request.get('data_type', request.get('type', 'uint16')),
                request.get('scale', 1),
                request.get('offset', 0),
                request.get('byte_order', 'big'),
                request.get('word_order', 'big')
            )
            count = len(raw) // 2
            function = response['function']
            if function is None:
                function = 6 if count == 1 else 16
            response['function'] = self._as_int(function)
            response['count'] = count

            start_ms = self._ticks_ms()
            await self._acquire_bus()
            try:
                await self._modbus_write(
                    response['port'],
                    self._as_int(response['slave']),
                    response['function'],
                    self._as_int(response['address']),
                    raw
                )
            finally:
                self._release_bus()

            response.update({
                'ok': True,
                'value': request.get('values', request.get('value')),
                'raw': self._hex(raw)
            })
        except Exception as exc:
            response['error'] = str(exc)
        finally:
            self._record_request_result(response, start_ms if 'start_ms' in locals() else None)

        return response

    def diagnostics_payload(self):
        return {
            'rs485_last_ok': self._last_request.get('ok'),
            'rs485_last_operation': self._last_request.get('operation', ''),
            'rs485_last_address': self._last_request.get('address', ''),
            'rs485_last_error': self._last_request.get('error', ''),
            'rs485_last_latency_ms': self._last_request.get('latency_ms', 0)
        }

    def _record_request_result(self, response, start_ms):
        latency_ms = 0
        if start_ms is not None:
            latency_ms = max(0, self._ticks_diff(self._ticks_ms(), start_ms))
        response['latency_ms'] = latency_ms
        self._last_request = {
            'ok': bool(response.get('ok')),
            'operation': response.get('operation', ''),
            'address': response.get('address', ''),
            'error': response.get('error', ''),
            'latency_ms': latency_ms
        }

    def _entity_request(self, entity):
        return {
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

    def _decode_entity_value(self, raw, request):
        value = self._decode_registers(
            raw,
            request.get('data_type', request.get('type', 'uint16')),
            request.get('byte_order', 'big'),
            request.get('word_order', 'big')
        )
        if not isinstance(value, str):
            value = (value * request.get('scale', 1)) + request.get('offset', 0)
        return value

    def _poll_groups(self, entities):
        groups = []
        current = []

        for entity in sorted(entities, key=self._entity_group_sort_key):
            if not current or self._can_extend_group(current, entity):
                current.append(entity)
            else:
                groups.append(current)
                current = [entity]

        if current:
            groups.append(current)

        return groups

    def _entity_group_sort_key(self, entity):
        request = self._entity_request(entity)
        return (
            request['port'],
            self._as_int(request['slave']),
            self._as_int(request['function']),
            self._entity_pollinterval(entity),
            self._as_int(request['address'] or 0)
        )

    def _can_extend_group(self, current, entity):
        first = self._entity_request(current[0])
        request = self._entity_request(entity)

        if request['address'] is None or first['address'] is None:
            return False

        if request['port'] != first['port']:
            return False
        if self._as_int(request['slave']) != self._as_int(first['slave']):
            return False
        if self._as_int(request['function']) != self._as_int(first['function']):
            return False
        if self._entity_pollinterval(entity) != self._entity_pollinterval(current[0]):
            return False

        current_start = self._as_int(self._entity_request(current[0])['address'])
        current_end = current_start
        for item in current:
            item_request = self._entity_request(item)
            current_end = max(
                current_end,
                self._as_int(item_request['address']) + self._as_int(item_request['count'])
            )

        address = self._as_int(request['address'])
        end_address = address + self._as_int(request['count'])
        if address != current_end:
            return False

        return (end_address - current_start) <= self._max_group_registers()

    def _max_group_registers(self):
        rs485 = self.device.get('rs485', {})
        return rs485.get('max_group_registers', DEFAULT_MAX_GROUP_REGISTERS)

    def _ticks_ms(self):
        if hasattr(time, 'ticks_ms'):
            return time.ticks_ms()
        return int(time.time() * 1000)

    def _ticks_diff(self, end, start):
        if hasattr(time, 'ticks_diff'):
            return time.ticks_diff(end, start)
        return end - start

    def _is_write_request(self, request):
        operation = request.get('operation', request.get('action', request.get('mode')))
        if operation is None:
            return 'value' in request or 'values' in request
        return str(operation).lower() in ('write', 'set')

    def _as_int(self, value):
        if isinstance(value, str):
            value = value.strip().lower()
            if value.startswith('x'):
                value = '0' + value
            return int(value, 0)
        return int(value)

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

    async def _modbus_write(self, port_name, slave, function, address, raw):
        port = self.devchar['ports'].get(port_name)
        if not port:
            raise ValueError('unknown port ' + str(port_name))
        if len(raw) % 2:
            raise ValueError('write data must contain whole registers')

        count = len(raw) // 2
        if function == 6:
            if count != 1:
                raise ValueError('function 6 writes exactly one register')
            request = bytes([
                slave & 0xff,
                function & 0xff,
                (address >> 8) & 0xff,
                address & 0xff
            ]) + raw
            expected = 8
        elif function == 16:
            request = bytes([
                slave & 0xff,
                function & 0xff,
                (address >> 8) & 0xff,
                address & 0xff,
                (count >> 8) & 0xff,
                count & 0xff,
                len(raw) & 0xff
            ]) + raw
            expected = 8
        else:
            raise ValueError('unsupported write function ' + str(function))

        request += self._crc_bytes(request)

        uart = port['uart']
        self._drain(uart)
        self._set_tx(port, True)
        uart.write(request)
        if hasattr(uart, 'flush'):
            uart.flush()
        await asyncio.sleep_ms(port.get('turnaround_ms', 5))
        self._set_tx(port, False)

        reply = await self._read_exact(uart, expected, port.get('timeout_ms', DEFAULT_TIMEOUT_MS))
        if len(reply) < expected:
            raise ValueError('timeout')
        if self._crc(reply[:-2]) != (reply[-2] | (reply[-1] << 8)):
            raise ValueError('crc mismatch')
        if reply[0] != slave:
            raise ValueError('unexpected slave')
        if reply[1] == (function | 0x80):
            raise ValueError('modbus exception ' + str(reply[2]))
        if reply[1] != function:
            raise ValueError('unexpected function')

        if function == 6:
            if reply[2:6] != request[2:6]:
                raise ValueError('unexpected write echo')
        elif reply[2] != ((address >> 8) & 0xff) or reply[3] != (address & 0xff):
            raise ValueError('unexpected write address')
        elif reply[4] != ((count >> 8) & 0xff) or reply[5] != (count & 0xff):
            raise ValueError('unexpected write count')

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
            'topic': ha_response_topic('sensor', self._deviceid, self.device['uuid']),
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

    def _encode_registers(self, values, data_type, scale, offset, byte_order, word_order):
        raw = b''
        for value in values:
            raw += self._encode_value(value, data_type, scale, offset)

        if len(raw) == 4 and word_order == 'little':
            raw = raw[2:4] + raw[0:2]

        if byte_order == 'little':
            words = []
            for i in range(0, len(raw), 2):
                words.append(bytes([raw[i + 1], raw[i]]))
            raw = b''.join(words)

        return raw

    def _encode_value(self, value, data_type, scale, offset):
        if data_type == 'ascii':
            raise ValueError('ascii writes are not supported')

        scale = scale or 1
        value = int(round((float(value) - offset) / scale))

        if data_type == 'int16':
            if value < 0:
                value += 65536
            return bytes([(value >> 8) & 0xff, value & 0xff])
        if data_type == 'uint32' or data_type == 'int32':
            if value < 0:
                value += 4294967296
            return bytes([
                (value >> 24) & 0xff,
                (value >> 16) & 0xff,
                (value >> 8) & 0xff,
                value & 0xff
            ])
        if data_type == 'float32':
            raise ValueError('float32 writes are not supported')

        return bytes([(value >> 8) & 0xff, value & 0xff])

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
