"""Read-only Bosch EMS boiler sensor module.

The EMS interface board presents the boiler bus as 3.3V TTL UART. This driver
listens for broadcast monitor telegrams and publishes configured values to MQTT.
It deliberately does not acknowledge polls, fetch telegrams, or write settings.
"""

from machine import UART, Pin
try:
    from .base import DeviceDriver
    from .base import ha_safe_id
    from .base import sensor_discovery_payload
    from .logging import log_output
except ImportError:
    from base import DeviceDriver
    from base import ha_safe_id
    from base import sensor_discovery_payload
    from logging import log_output
import asyncio
import time


DEVICE_TYPE = {
    'class': 'sensor',
    'subclass': {
        'EMS-Boiler': {
            'entities': {
                'energy',
                'memory_value',
                'power',
                'pressure',
                'temperature'
            }
        }
    },
    'ha_discovery': True,
    'ha_subscribe': False,
    'local_init': False
}


DEFAULT_UART = 0
DEFAULT_RX = 1
DEFAULT_BAUDRATE = 9600
DEFAULT_FRAME_GAP_MS = 20
DEFAULT_POLL_MS = 5
DEFAULT_MAX_FRAME_BYTES = 96

BOILER_ID = 0x08


EMS_CRC_TABLE = (
    0x00, 0x02, 0x04, 0x06, 0x08, 0x0A, 0x0C, 0x0E,
    0x10, 0x12, 0x14, 0x16, 0x18, 0x1A, 0x1C, 0x1E,
    0x20, 0x22, 0x24, 0x26, 0x28, 0x2A, 0x2C, 0x2E,
    0x30, 0x32, 0x34, 0x36, 0x38, 0x3A, 0x3C, 0x3E,
    0x40, 0x42, 0x44, 0x46, 0x48, 0x4A, 0x4C, 0x4E,
    0x50, 0x52, 0x54, 0x56, 0x58, 0x5A, 0x5C, 0x5E,
    0x60, 0x62, 0x64, 0x66, 0x68, 0x6A, 0x6C, 0x6E,
    0x70, 0x72, 0x74, 0x76, 0x78, 0x7A, 0x7C, 0x7E,
    0x80, 0x82, 0x84, 0x86, 0x88, 0x8A, 0x8C, 0x8E,
    0x90, 0x92, 0x94, 0x96, 0x98, 0x9A, 0x9C, 0x9E,
    0xA0, 0xA2, 0xA4, 0xA6, 0xA8, 0xAA, 0xAC, 0xAE,
    0xB0, 0xB2, 0xB4, 0xB6, 0xB8, 0xBA, 0xBC, 0xBE,
    0xC0, 0xC2, 0xC4, 0xC6, 0xC8, 0xCA, 0xCC, 0xCE,
    0xD0, 0xD2, 0xD4, 0xD6, 0xD8, 0xDA, 0xDC, 0xDE,
    0xE0, 0xE2, 0xE4, 0xE6, 0xE8, 0xEA, 0xEC, 0xEE,
    0xF0, 0xF2, 0xF4, 0xF6, 0xF8, 0xFA, 0xFC, 0xFE,
    0x19, 0x1B, 0x1D, 0x1F, 0x11, 0x13, 0x15, 0x17,
    0x09, 0x0B, 0x0D, 0x0F, 0x01, 0x03, 0x05, 0x07,
    0x39, 0x3B, 0x3D, 0x3F, 0x31, 0x33, 0x35, 0x37,
    0x29, 0x2B, 0x2D, 0x2F, 0x21, 0x23, 0x25, 0x27,
    0x59, 0x5B, 0x5D, 0x5F, 0x51, 0x53, 0x55, 0x57,
    0x49, 0x4B, 0x4D, 0x4F, 0x41, 0x43, 0x45, 0x47,
    0x79, 0x7B, 0x7D, 0x7F, 0x71, 0x73, 0x75, 0x77,
    0x69, 0x6B, 0x6D, 0x6F, 0x61, 0x63, 0x65, 0x67,
    0x99, 0x9B, 0x9D, 0x9F, 0x91, 0x93, 0x95, 0x97,
    0x89, 0x8B, 0x8D, 0x8F, 0x81, 0x83, 0x85, 0x87,
    0xB9, 0xBB, 0xBD, 0xBF, 0xB1, 0xB3, 0xB5, 0xB7,
    0xA9, 0xAB, 0xAD, 0xAF, 0xA1, 0xA3, 0xA5, 0xA7,
    0xD9, 0xDB, 0xDD, 0xDF, 0xD1, 0xD3, 0xD5, 0xD7,
    0xC9, 0xCB, 0xCD, 0xCF, 0xC1, 0xC3, 0xC5, 0xC7,
    0xF9, 0xFB, 0xFD, 0xFF, 0xF1, 0xF3, 0xF5, 0xF7,
    0xE9, 0xEB, 0xED, 0xEF, 0xE1, 0xE3, 0xE5, 0xE7
)


def supports(device):
    return (
        device['type']['class'] == 'sensor' and
        device['type']['subclass'] == 'EMS-Boiler'
    )


def _as_pin(value):
    if value is None:
        return None
    return Pin(value)


def setup(device, index):
    ems = device.get('ems', {})
    uart_args = {
        'baudrate': ems.get('baudrate', DEFAULT_BAUDRATE),
        'bits': ems.get('bits', 8),
        'parity': ems.get('parity', None),
        'stop': ems.get('stop', 1),
        'rx': _as_pin(ems.get('rx', DEFAULT_RX))
    }

    if 'tx' in ems:
        uart_args['tx'] = _as_pin(ems.get('tx'))

    uart = UART(ems.get('uart', DEFAULT_UART), **uart_args)
    return {
        'uuid': device['uuid'],
        'index': index,
        'uart': uart,
        'driver': EMSBoilerDriver(device, {'uart': uart})
    }


def create_driver(device, device_char):
    return device_char['driver']


class EMSBoilerDriver(DeviceDriver):
    def __init__(self, device, device_char):
        super().__init__(device, device_char)
        self._running = False
        self._publish_callable = None
        self._deviceid = None
        self._log_callable = None
        self._values = {}
        self._diagnostics = {
            'ems_last_ok': None,
            'ems_last_type': '',
            'ems_last_src': '',
            'ems_last_error': '',
            'ems_frames': 0,
            'ems_crc_errors': 0
        }

        for e in self.device.get('entities', {}):
            entity = self.device['entities'][str(e)]
            self._values[entity.get('key', entity['class'])] = entity.get('value', None)

    def get_discovery_payloads(self, deviceid, ha_devicename):
        payload_discovery = {}
        payload_entities = self.get_state_payload()

        for e in self.device['entities']:
            entity = self.device['entities'][str(e)].copy()
            key = entity.get('key', entity['class'])
            discovery_id = ha_safe_id(key)
            entity['ha_id'] = key
            payload_discovery[discovery_id] = sensor_discovery_payload(
                self.device,
                entity,
                key,
                e,
                deviceid,
                ha_devicename
            )

        return payload_discovery, payload_entities

    def get_state_payload(self):
        payload = {}
        for e in self.device.get('entities', {}):
            entity = self.device['entities'][str(e)]
            key = entity.get('key', entity['class'])
            if key in self._diagnostics:
                payload[key] = self._diagnostics[key]
            else:
                payload[key] = self._values.get(key, entity.get('value', None))
        return payload

    def start(self, publish_callable, deviceid, log_callable=None):
        self._publish_callable = publish_callable
        self._deviceid = deviceid
        self._log_callable = log_callable

        if self._running:
            return
        self._running = True

        async def read_loop():
            uart = self.devchar['uart']
            buffer = bytearray()
            last_rx = self._ticks_ms()
            ems_cfg = self.device.get('ems', {})
            frame_gap_ms = ems_cfg.get('frame_gap_ms', DEFAULT_FRAME_GAP_MS)
            poll_ms = ems_cfg.get('poll_ms', DEFAULT_POLL_MS)
            max_frame_bytes = ems_cfg.get('max_frame_bytes', DEFAULT_MAX_FRAME_BYTES)

            while True:
                try:
                    available = uart.any()
                    if available:
                        chunk = uart.read(available)
                        if chunk:
                            buffer.extend(chunk)
                            if len(buffer) > max_frame_bytes:
                                buffer = buffer[-max_frame_bytes:]
                            last_rx = self._ticks_ms()

                    if buffer and self._ticks_diff(self._ticks_ms(), last_rx) >= frame_gap_ms:
                        frame = bytes(buffer)
                        buffer = bytearray()
                        changed = self._process_frame(frame)
                        if changed:
                            self.publish_state(publish_callable, deviceid)
                except Exception as exc:
                    self._record_error('read error ' + str(exc))

                await asyncio.sleep_ms(poll_ms)

        try:
            asyncio.create_task(read_loop())
        except Exception as exc:
            self._record_error('start error ' + str(exc))

    def _process_frame(self, frame):
        if len(frame) < 6:
            return False

        if self._crc(frame[:-1]) != frame[-1]:
            self._diagnostics['ems_crc_errors'] += 1
            self._diagnostics['ems_last_ok'] = False
            self._diagnostics['ems_last_error'] = 'crc mismatch'
            self._log('crc mismatch', 'DEBUG')
            return False

        telegram = self._parse_telegram(frame)
        if not telegram:
            return False

        src = telegram['src'] & 0x7f
        if src != self.device.get('boiler_id', BOILER_ID):
            return False

        self._diagnostics['ems_frames'] += 1
        self._diagnostics['ems_last_ok'] = True
        self._diagnostics['ems_last_error'] = ''
        self._diagnostics['ems_last_src'] = self._hex_byte(telegram['src'])
        self._diagnostics['ems_last_type'] = self._hex_type(telegram['type'])

        values = self._decode_values(telegram)
        return self._update_values(values)

    def _parse_telegram(self, frame):
        src = frame[0]
        dest = frame[1]

        if frame[2] == 0xff:
            if len(frame) < 8:
                return None
            telegram_type = (frame[4] << 8) | frame[5]
            offset = frame[3]
            data = frame[6:-1]
        else:
            telegram_type = frame[2]
            offset = frame[3]
            data = frame[4:-1]

        return {
            'src': src,
            'dest': dest,
            'type': telegram_type,
            'offset': offset,
            'data': data
        }

    def _decode_values(self, telegram):
        if telegram['offset'] != 0:
            return {}

        data = telegram['data']
        telegram_type = telegram['type']
        values = {}

        if telegram_type == 0x18:
            self._decode_fast(data, values)
        elif telegram_type == 0x19:
            self._decode_slow(data, values)
        elif telegram_type == 0x34:
            self._decode_ww(data, values)
        elif telegram_type == 0xE4:
            self._decode_fast_plus(data, values)
        elif telegram_type == 0xE5:
            self._decode_slow_plus(data, values)
        elif telegram_type == 0xE9:
            self._decode_ww_plus(data, values)

        return values

    def _decode_fast(self, data, values):
        self._put(values, 'selflowtemp', self._u8(data, 0))
        self._put(values, 'curflowtemp', self._temp_u16(data, 1))
        self._put(values, 'selburnpow', self._u8(data, 3))
        self._put(values, 'curburnpow', self._u8(data, 4))
        state = self._u8(data, 5)
        if state is not None:
            self._put(values, 'heatingactive', bool(state & 0x01))
            self._put(values, 'tapwateractive', bool(state & 0x02))
            self._put(values, 'flameactive', bool(state & 0x08))
        flags = self._u8(data, 7)
        if flags is not None:
            self._put(values, 'burngas', bool(flags & 0x01))
            self._put(values, 'heatingpump', bool(flags & 0x20))
            self._put(values, 'dhw.3wayvalve', bool(flags & 0x40))
        self._put(values, 'dhw.storagetemp1', self._temp_u16(data, 9))
        self._put(values, 'dhw.storagetemp2', self._temp_u16(data, 11))
        self._put(values, 'rettemp', self._temp_u16(data, 13))
        self._put(values, 'flamecurr', self._scaled_u16(data, 15, 0.1))
        self._put(values, 'syspress', self._scaled_u8(data, 17, 0.1, (0xff,)))
        self._put(values, 'servicecode', self._ascii(data, 18, 2))
        self._put(values, 'servicecodenumber', self._u16(data, 20))
        charge_pump = self._bit(data, 23, 0)
        if charge_pump is not None:
            self._put(values, 'dhw.chargepump', charge_pump)

    def _decode_slow(self, data, values):
        self._put(values, 'outdoortemp', self._temp_i16(data, 0))
        self._put(values, 'boiltemp', self._temp_u16(data, 2))
        self._put(values, 'exhausttemp', self._temp_u16(data, 4))
        self._put(values, 'heatingpumpmod', self._u8(data, 9))
        self._put(values, 'burnstarts', self._u24(data, 10))
        self._put(values, 'burnworkmin', self._u24(data, 13))
        self._put(values, 'burn2workmin', self._u24(data, 16))
        self._put(values, 'heatworkmin', self._u24(data, 19))
        self._put(values, 'heatstarts', self._u24(data, 22))
        self._put(values, 'switchtemp', self._temp_u16(data, 25))

    def _decode_ww(self, data, values):
        self._put(values, 'dhw.settemp', self._u8(data, 0))
        self._put(values, 'dhw.curtemp', self._temp_u16(data, 1))
        self._put(values, 'dhw.curtemp2', self._temp_u16(data, 3))
        self._put(values, 'dhw.type', self._u8(data, 8))
        self._put(values, 'dhw.curflow', self._scaled_u8(data, 9, 0.1))
        self._put(values, 'dhw.workm', self._u24(data, 10))
        self._put(values, 'dhw.starts', self._u24(data, 13))
        self._put(values, 'dhw.solartemp', self._temp_u16(data, 17))
        self._decode_ww_flags(data, values, 5, None)

    def _decode_fast_plus(self, data, values):
        self._put(values, 'servicecode', self._ascii(data, 1, 3))
        self._put(values, 'servicecodenumber', self._u16(data, 4))
        self._put(values, 'selflowtemp', self._u8(data, 6))
        self._put(values, 'curflowtemp', self._temp_u16(data, 7))
        self._put(values, 'selburnpow', self._u8(data, 9))
        self._put(values, 'curburnpow', self._u8(data, 10))
        flags = self._u8(data, 11)
        if flags is not None:
            self._put(values, 'burngas', bool(flags & 0x01))
            self._put(values, 'heatingactive', bool(flags & 0x02))
            self._put(values, 'tapwateractive', bool(flags & 0x04))
            self._put(values, 'dhw.3wayvalve', bool(flags & 0x04))
        self._put(values, 'rettemp', self._temp_u16(data, 17, (0, 0x8000)))
        self._put(values, 'flamecurr', self._scaled_u16(data, 19, 0.1))
        self._put(values, 'syspress', self._scaled_u8(data, 21, 0.1, (0, 0xff)))
        self._put(values, 'heatblock', self._temp_u16(data, 23))
        self._put(values, 'headertemp', self._temp_u16(data, 25))
        self._put(values, 'exhausttemp', self._temp_u16(data, 31))
        self._put(values, 'pc0flow', self._i16(data, 36))

    def _decode_slow_plus(self, data, values):
        flags = self._u8(data, 2)
        if flags is not None:
            self._put(values, 'fanwork', bool(flags & 0x04))
            self._put(values, 'ignwork', bool(flags & 0x08))
            self._put(values, 'heatingpump', bool(flags & 0x20))
            self._put(values, 'dhw.circ', bool(flags & 0x80))
        self._put(values, 'exhausttemp', self._temp_u16(data, 6))
        self._put(values, 'burnstarts', self._u24(data, 10))
        self._put(values, 'burnworkmin', self._u24(data, 13))
        self._put(values, 'burn2workmin', self._u24(data, 16))
        self._put(values, 'heatworkmin', self._u24(data, 19))
        self._put(values, 'heatstarts', self._u24(data, 22))
        self._put(values, 'heatingpumpmod', self._u8(data, 25))

    def _decode_ww_plus(self, data, values):
        self._put(values, 'dhw.settemp', self._u8(data, 0))
        self._put(values, 'dhw.curtemp', self._temp_u16(data, 1))
        self._put(values, 'dhw.curtemp2', self._temp_u16(data, 3))
        self._put(values, 'dhw.curflow', self._scaled_u8(data, 11, 0.1))
        self._put(values, 'dhw.workm', self._u24(data, 14))
        self._put(values, 'dhw.starts', self._u24(data, 17))
        self._decode_ww_flags(data, values, 12, 13)

    def _decode_ww_flags(self, data, values, primary_offset, secondary_offset):
        primary = self._u8(data, primary_offset)
        if primary is not None:
            self._put(values, 'dhw.onetime', bool(primary & 0x04 if secondary_offset is not None else primary & 0x02))
            self._put(values, 'dhw.disinfecting', bool(primary & 0x08 if secondary_offset is not None else primary & 0x04))
            self._put(values, 'dhw.charging', bool(primary & 0x10 if secondary_offset is not None else primary & 0x08))
            if secondary_offset is None:
                self._put(values, 'dhw.recharging', bool(primary & 0x10))
                self._put(values, 'dhw.tempok', bool(primary & 0x20))
                self._put(values, 'dhw.active', bool(primary & 0x40))

        secondary = self._u8(data, secondary_offset) if secondary_offset is not None else None
        if secondary is not None:
            self._put(values, 'dhw.recharging', bool(secondary & 0x10))
            self._put(values, 'dhw.tempok', bool(secondary & 0x20))
            self._put(values, 'dhw.circ', bool(secondary & 0x04))

    def _update_values(self, values):
        changed = False
        for key in values:
            if key in self._values and values[key] is not None and self._values.get(key) != values[key]:
                self._values[key] = values[key]
                changed = True

        return changed

    def _put(self, values, key, value):
        if value is not None:
            values[key] = value

    def _record_error(self, message):
        self._diagnostics['ems_last_ok'] = False
        self._diagnostics['ems_last_error'] = message
        self._log(message, 'ERROR')

    def _log(self, message, logtype='INFO'):
        if self._log_callable:
            self._log_callable('Local', 'EMS-Boiler', {'log': message}, logtype)
        else:
            log_output('Local', 'EMS-Boiler', {'log': message}, logtype)

    def _crc(self, data):
        crc = 0
        for byte in data:
            crc = EMS_CRC_TABLE[crc] ^ byte
        return crc

    def _u8(self, data, offset, missing=(0xff,)):
        if offset is None or offset >= len(data):
            return None
        value = data[offset]
        if value in missing:
            return None
        return value

    def _u16(self, data, offset, missing=(0x8000, 0x7fff, 0xffff)):
        if offset is None or offset + 1 >= len(data):
            return None
        value = (data[offset] << 8) | data[offset + 1]
        if value in missing:
            return None
        return value

    def _i16(self, data, offset, missing=(0x8000, 0x7fff, 0xffff)):
        value = self._u16(data, offset, missing)
        if value is None:
            return None
        if value & 0x8000:
            value -= 0x10000
        return value

    def _u24(self, data, offset, missing=(0x800000, 0x7fffff, 0xffffff)):
        if offset is None or offset + 2 >= len(data):
            return None
        value = (data[offset] << 16) | (data[offset + 1] << 8) | data[offset + 2]
        if value in missing:
            return None
        return value

    def _scaled_u8(self, data, offset, scale, missing=(0xff,)):
        value = self._u8(data, offset, missing)
        if value is None:
            return None
        return self._round(value * scale)

    def _scaled_u16(self, data, offset, scale, missing=(0x8000, 0x7fff, 0xffff)):
        value = self._u16(data, offset, missing)
        if value is None:
            return None
        return self._round(value * scale)

    def _temp_u16(self, data, offset, missing=(0x8000, 0x8300, 0x7fff, 0xffff)):
        return self._scaled_u16(data, offset, 0.1, missing)

    def _temp_i16(self, data, offset, missing=(0x8000, 0x8300, 0x7fff, 0xffff)):
        value = self._i16(data, offset, missing)
        if value is None:
            return None
        return self._round(value * 0.1)

    def _bit(self, data, offset, bit):
        value = self._u8(data, offset)
        if value is None:
            return None
        return bool(value & (1 << bit))

    def _ascii(self, data, offset, count):
        if offset is None or offset + count > len(data):
            return None
        text = ''
        for byte in data[offset:offset + count]:
            if byte in (0, 0xff):
                continue
            text += chr(byte)
        return text or None

    def _round(self, value):
        rounded = round(value, 1)
        if rounded == int(rounded):
            return int(rounded)
        return rounded

    def _ticks_ms(self):
        if hasattr(time, 'ticks_ms'):
            return time.ticks_ms()
        return int(time.time() * 1000)

    def _ticks_diff(self, end, start):
        if hasattr(time, 'ticks_diff'):
            return time.ticks_diff(end, start)
        return end - start

    def _hex_byte(self, value):
        return '0x' + ('0' + hex(value & 0xff)[2:])[-2:]

    def _hex_type(self, value):
        if value <= 0xff:
            return self._hex_byte(value)
        return '0x' + ('000' + hex(value)[2:])[-4:]
