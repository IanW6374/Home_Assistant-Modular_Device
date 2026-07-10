"""MAX31865 PT1000 RTD temperature sensor module."""

try:
    from math import sqrt
except ImportError:
    sqrt = None

from machine import Pin, SPI
try:
    from .base import DeviceDriver
    from .base import ha_safe_id
    from .base import sensor_discovery_payload
    from .logging import log_output
    from .spi_bus import get_spi
except ImportError:
    from base import DeviceDriver
    from base import ha_safe_id
    from base import sensor_discovery_payload
    from logging import log_output
    from spi_bus import get_spi
import asyncio


DEVICE_TYPE = {
    'class': 'sensor',
    'subclass': {
        'MAX31865-PT1000': {
            'entities': {
                'memory_value',
                'temperature'
            }
        }
    },
    'ha_discovery': True,
    'ha_subscribe': False,
    'local_init': False
}


REG_CONFIG = 0x00
REG_RTD_MSB = 0x01
REG_FAULT_STATUS = 0x07

CONFIG_BIAS = 0x80
CONFIG_AUTO_CONVERT = 0x40
CONFIG_ONE_SHOT = 0x20
CONFIG_3WIRE = 0x10
CONFIG_FAULT_CLEAR = 0x02
CONFIG_FILTER_50HZ = 0x01

RTD_A = 3.9083e-3
RTD_B = -5.775e-7
RTD_C = -4.183e-12

DEFAULT_SPI = 0
DEFAULT_SCK = 2
DEFAULT_MOSI = 3
DEFAULT_MISO = 4
DEFAULT_CS = 5
DEFAULT_BAUDRATE = 1000000
DEFAULT_RTD_NOMINAL = 1000.0
DEFAULT_REF_RESISTOR = 4300.0
DEFAULT_POLL_INTERVAL = 30


def supports(device):
    return (
        device['type']['class'] == 'sensor' and
        device['type']['subclass'] == 'MAX31865-PT1000'
    )


def setup(device, index):
    cfg = device.get('max31865', {})
    spi = get_spi(cfg, {
        'spi': DEFAULT_SPI,
        'baudrate': DEFAULT_BAUDRATE,
        'polarity': 0,
        'phase': 1,
        'bits': 8,
        'firstbit': SPI.MSB,
        'sck': DEFAULT_SCK,
        'mosi': DEFAULT_MOSI,
        'miso': DEFAULT_MISO
    })
    cs = Pin(cfg.get('cs', DEFAULT_CS), Pin.OUT)
    cs.value(1)

    return {
        'uuid': device['uuid'],
        'index': index,
        'spi': spi,
        'cs': cs
    }


def create_driver(device, device_char):
    return MAX31865PT1000Driver(device, device_char)


class MAX31865PT1000Driver(DeviceDriver):
    def __init__(self, device, device_char):
        super().__init__(device, device_char)
        cfg = device.get('max31865', {})
        self.rtd_nominal = float(cfg.get('rtd_nominal', DEFAULT_RTD_NOMINAL))
        self.ref_resistor = float(cfg.get('ref_resistor', DEFAULT_REF_RESISTOR))
        self.wires = int(cfg.get('wires', 2))
        self.filter_hz = int(cfg.get('filter_hz', 50))
        self.auto_convert = bool(cfg.get('auto_convert', False))
        self.precision = int(cfg.get('precision', 2))
        self._configured = False
        self._log_callable = None

    def get_discovery_payloads(self, deviceid, ha_devicename):
        payload_discovery = {}
        payload_entities = self.get_state_payload()

        for e in self.device['entities']:
            entity = self.device['entities'][str(e)].copy()
            key = entity.get('key', entity['class'])
            entity['ha_id'] = key
            payload_discovery[ha_safe_id(key)] = sensor_discovery_payload(
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
        for e in self.device['entities']:
            entity = self.device['entities'][str(e)]
            payload[entity.get('key', entity['class'])] = entity.get('value', None)
        return payload

    def start(self, publish_callable, deviceid, log_callable=None):
        self._log_callable = log_callable

        async def measure_loop():
            self._configure()
            while True:
                try:
                    started = self._ticks_ms()
                    reading = self.read()
                    self._update_entities(reading)
                    self.mark_read_ok(self._ticks_diff(self._ticks_ms(), started))
                    self.publish_state(publish_callable, deviceid)
                except Exception as exc:
                    self.mark_read_error(exc)
                    self._update_key('fault', str(exc))
                    self._log('Read error ' + str(exc), 'ERROR')

                await asyncio.sleep(self.device.get('pollinterval', DEFAULT_POLL_INTERVAL))

        try:
            asyncio.create_task(measure_loop())
        except Exception as exc:
            self._log('Start error ' + str(exc), 'ERROR')

    def read(self):
        self._configure()
        raw = self._read_rtd_raw()
        resistance = self._raw_to_resistance(raw)
        fault = self._read_u8(REG_FAULT_STATUS)
        temperature = self._resistance_to_temperature(resistance)

        return {
            'temperature': self._round(temperature),
            'resistance': self._round(resistance),
            'rtd_raw': raw,
            'fault': self._fault_text(fault),
            'fault_code': fault
        }

    def _configure(self):
        config = CONFIG_BIAS | CONFIG_FAULT_CLEAR
        if self.auto_convert:
            config |= CONFIG_AUTO_CONVERT
        if self.wires == 3:
            config |= CONFIG_3WIRE
        if self.filter_hz == 50:
            config |= CONFIG_FILTER_50HZ

        self._write_u8(REG_CONFIG, config)
        self._configured = True

    def _read_rtd_raw(self):
        if not self.auto_convert:
            config = self._read_u8(REG_CONFIG)
            self._write_u8(REG_CONFIG, config | CONFIG_BIAS | CONFIG_ONE_SHOT | CONFIG_FAULT_CLEAR)
            self._sleep_ms(65)

        data = self._read(REG_RTD_MSB, 2)
        value = ((data[0] << 8) | data[1]) >> 1
        return value

    def _raw_to_resistance(self, raw):
        return (raw * self.ref_resistor) / 32768.0

    def _resistance_to_temperature(self, resistance):
        ratio = resistance / self.rtd_nominal

        if ratio >= 1.0 and sqrt:
            discriminant = (RTD_A * RTD_A) - (4 * RTD_B * (1 - ratio))
            return (-RTD_A + sqrt(discriminant)) / (2 * RTD_B)

        return self._temperature_by_search(resistance)

    def _temperature_by_search(self, resistance):
        low = -200.0
        high = 850.0
        for _ in range(32):
            mid = (low + high) / 2
            mid_resistance = self._temperature_to_resistance(mid)
            if mid_resistance < resistance:
                low = mid
            else:
                high = mid
        return (low + high) / 2

    def _temperature_to_resistance(self, temperature):
        if temperature >= 0:
            return self.rtd_nominal * (
                1 + (RTD_A * temperature) + (RTD_B * temperature * temperature)
            )

        return self.rtd_nominal * (
            1 +
            (RTD_A * temperature) +
            (RTD_B * temperature * temperature) +
            (RTD_C * (temperature - 100) * temperature * temperature * temperature)
        )

    def _update_entities(self, reading):
        for key in reading:
            self._update_key(key, reading[key])

    def _update_key(self, key, value):
        for e in self.device['entities']:
            entity = self.device['entities'][str(e)]
            if entity.get('key', entity['class']) == key:
                entity['value'] = value

    def _fault_text(self, fault):
        if not fault:
            return ''

        names = []
        if fault & 0x80:
            names.append('RTD high threshold')
        if fault & 0x40:
            names.append('RTD low threshold')
        if fault & 0x20:
            names.append('REFIN- > 0.85 x VBIAS')
        if fault & 0x10:
            names.append('REFIN- < 0.85 x VBIAS')
        if fault & 0x08:
            names.append('RTDIN- < 0.85 x VBIAS')
        if fault & 0x04:
            names.append('over/under voltage')

        return ', '.join(names) or 'unknown fault ' + str(fault)

    def _write_u8(self, register, value):
        self._select()
        try:
            self.devchar['spi'].write(bytes([register | 0x80, value & 0xff]))
        finally:
            self._deselect()

    def _read_u8(self, register):
        return self._read(register, 1)[0]

    def _read(self, register, count):
        self._select()
        try:
            self.devchar['spi'].write(bytes([register & 0x7f]))
            data = self.devchar['spi'].read(count)
        finally:
            self._deselect()
        return data

    def _select(self):
        self.devchar['cs'].value(0)

    def _deselect(self):
        self.devchar['cs'].value(1)

    def _sleep_ms(self, ms):
        try:
            import time
            if hasattr(time, 'sleep_ms'):
                time.sleep_ms(ms)
            else:
                time.sleep(ms / 1000)
        except Exception:
            pass

    def _ticks_ms(self):
        try:
            import time
            if hasattr(time, 'ticks_ms'):
                return time.ticks_ms()
            return int(time.time() * 1000)
        except Exception:
            return 0

    def _ticks_diff(self, end, start):
        try:
            import time
            if hasattr(time, 'ticks_diff'):
                return time.ticks_diff(end, start)
        except Exception:
            pass
        return end - start

    def _round(self, value):
        return round(value, self.precision)

    def _log(self, message, logtype='INFO'):
        if self._log_callable:
            self._log_callable('Local', 'MAX31865-PT1000', {'log': message}, logtype)
        else:
            log_output('Local', 'MAX31865-PT1000', {'log': message}, logtype)
