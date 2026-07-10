"""Grove MCP6002 AC voltage sensor module.

Samples a biased AC waveform with the Pico ADC, removes the DC midpoint, and
publishes a calibrated RMS voltage. The optional threshold entity is exposed as
a Home Assistant binary_sensor while sharing the same MQTT state payload.
"""

from machine import ADC, Pin
try:
    from .base import DeviceDriver
    from .base import ha_device_topic
    from .base import ha_safe_id
    from .base import ha_unique_id
    from .base import sensor_discovery_payload
    from .base import homeassistant_origin_info
    from .logging import log_output
except ImportError:
    from base import DeviceDriver
    from base import ha_device_topic
    from base import ha_safe_id
    from base import ha_unique_id
    from base import sensor_discovery_payload
    from base import homeassistant_origin_info
    from logging import log_output
import asyncio
import time


DEVICE_TYPE = {
    'class': 'sensor',
    'subclass': {
        'Grove-AC-Voltage': {
            'entities': {
                'memory_value',
                'voltage'
            }
        }
    },
    'ha_discovery': True,
    'ha_subscribe': False,
    'local_init': False
}


DEFAULT_ADC_PIN = 26
DEFAULT_VREF = 3.3
DEFAULT_ADC_MAX = 65535
DEFAULT_SAMPLE_COUNT = 600
DEFAULT_SAMPLE_DELAY_US = 200
DEFAULT_POLL_INTERVAL = 5
DEFAULT_CALIBRATION = 700.0
DEFAULT_PRECISION = 1
DEFAULT_THRESHOLD = 180.0
DEFAULT_HYSTERESIS = 5.0


def supports(device):
    return (
        device['type']['class'] == 'sensor' and
        device['type']['subclass'] == 'Grove-AC-Voltage'
    )


def setup(device, index):
    cfg = device.get('ac_voltage', {})
    adc_pin = cfg.get('adc_pin', device.get('adc_pin', DEFAULT_ADC_PIN))
    return {
        'uuid': device['uuid'],
        'index': index,
        'adc': ADC(Pin(adc_pin))
    }


def create_driver(device, device_char):
    return GroveACVoltageDriver(device, device_char)


class GroveACVoltageDriver(DeviceDriver):
    def __init__(self, device, device_char):
        super().__init__(device, device_char)
        cfg = device.get('ac_voltage', {})
        self.vref = float(cfg.get('vref', DEFAULT_VREF))
        self.adc_max = float(cfg.get('adc_max', DEFAULT_ADC_MAX))
        self.sample_count = int(cfg.get('sample_count', DEFAULT_SAMPLE_COUNT))
        self.sample_delay_us = int(cfg.get('sample_delay_us', DEFAULT_SAMPLE_DELAY_US))
        self.calibration = float(cfg.get('calibration', DEFAULT_CALIBRATION))
        self.offset = float(cfg.get('offset', 0))
        self.precision = int(cfg.get('precision', DEFAULT_PRECISION))
        self.threshold = float(cfg.get('threshold', DEFAULT_THRESHOLD))
        self.hysteresis = float(cfg.get('hysteresis', DEFAULT_HYSTERESIS))
        self.threshold_key = cfg.get('threshold_key', 'ac_present')
        self._threshold_state = None
        self._log_callable = None

    def get_discovery_payloads(self, deviceid, ha_devicename):
        payload_discovery = {}
        payload_entities = self.get_state_payload()

        for e in self.device['entities']:
            entity = self.device['entities'][str(e)].copy()
            key = entity.get('key', entity['class'])
            entity['ha_id'] = key

            if entity.get('component') == 'binary_sensor':
                payload_discovery[ha_safe_id(key)] = self._binary_discovery_payload(
                    entity,
                    key,
                    deviceid,
                    ha_devicename
                )
            else:
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
            while True:
                try:
                    started = self._ticks_ms()
                    reading = self.read()
                    self._update_entities(reading)
                    self.mark_read_ok(self._ticks_diff(self._ticks_ms(), started))
                    self.publish_state(publish_callable, deviceid)
                except Exception as exc:
                    self.mark_read_error(exc)
                    self._update_key('ac_voltage_error', str(exc))
                    self._log('Read error ' + str(exc), 'ERROR')

                await asyncio.sleep(self.device.get('pollinterval', DEFAULT_POLL_INTERVAL))

        try:
            asyncio.create_task(measure_loop())
        except Exception as exc:
            self._log('Start error ' + str(exc), 'ERROR')

    def read(self):
        stats = self._sample_adc()
        sensor_rms = stats['rms_counts'] * (self.vref / self.adc_max)
        voltage = (sensor_rms * self.calibration) + self.offset
        voltage = max(0, voltage)
        voltage = round(voltage, self.precision)

        return {
            'voltage': voltage,
            self.threshold_key: self._threshold_value(voltage),
            'adc_rms': round(stats['rms_counts'], 2),
            'adc_midpoint': round(stats['midpoint'], 2),
            'adc_min': stats['minimum'],
            'adc_max': stats['maximum'],
            'ac_voltage_error': ''
        }

    def set(self, payload):
        if isinstance(payload, dict) and payload.get('operation') == 'calibrate':
            return self.set_calibration(payload)
        return None

    def set_calibration(self, payload):
        try:
            known_voltage = float(payload.get('known_voltage'))
        except Exception:
            return {'ok': False, 'error': 'known_voltage required'}

        state = self.get_state_payload()
        try:
            measured_voltage = float(payload.get('measured_voltage', state.get('voltage')))
        except Exception:
            measured_voltage = 0

        if measured_voltage <= 0:
            return {'ok': False, 'error': 'current voltage must be greater than zero'}

        self.calibration = round((self.calibration * known_voltage) / measured_voltage, 6)
        cfg = self.device.get('ac_voltage', {})
        cfg['calibration'] = self.calibration
        self._log('Calibration set to ' + str(self.calibration), 'INFO')
        return {
            'ok': True,
            'calibration': self.calibration,
            'known_voltage': known_voltage,
            'measured_voltage': measured_voltage
        }

    def _sample_adc(self):
        values = []
        total = 0
        minimum = None
        maximum = None

        for _ in range(self.sample_count):
            value = self.devchar['adc'].read_u16()
            values.append(value)
            total += value
            if minimum is None or value < minimum:
                minimum = value
            if maximum is None or value > maximum:
                maximum = value
            if self.sample_delay_us:
                self._sleep_us(self.sample_delay_us)

        midpoint = total / len(values)
        square_total = 0
        for value in values:
            delta = value - midpoint
            square_total += delta * delta

        return {
            'rms_counts': (square_total / len(values)) ** 0.5,
            'midpoint': midpoint,
            'minimum': minimum,
            'maximum': maximum
        }

    def _threshold_value(self, voltage):
        if self._threshold_state is None:
            self._threshold_state = voltage >= self.threshold
            return self._threshold_state

        if self._threshold_state:
            if voltage <= self.threshold - self.hysteresis:
                self._threshold_state = False
        elif voltage >= self.threshold:
            self._threshold_state = True

        return self._threshold_state

    def _binary_discovery_payload(self, entity, key, deviceid, ha_devicename):
        payload = {
            '_component': 'binary_sensor',
            '~': ha_device_topic(self.device['type']['class'], deviceid, self.device['uuid']),
            'stat_t': '~/state',
            'uniq_id': ha_unique_id(deviceid, self.device['uuid'], key),
            'name': self.device['name'] + ' ' + key,
            'value_template': "{{ 'ON' if value_json[" + repr(key) + "] else 'OFF' }}",
            'payload_on': 'ON',
            'payload_off': 'OFF',
            'dev': self.discovery_device_info(deviceid, ha_devicename),
            'o': homeassistant_origin_info()
        }

        device_class = entity.get('device_class')
        if device_class:
            payload['device_class'] = device_class
        if 'entity_category' in entity:
            payload['entity_category'] = entity['entity_category']
        if entity.get('entity_category') == 'diagnostic':
            payload['en'] = False

        return payload

    def _update_entities(self, reading):
        for key in reading:
            self._update_key(key, reading[key])

    def _update_key(self, key, value):
        for e in self.device['entities']:
            entity = self.device['entities'][str(e)]
            if entity.get('key', entity['class']) == key:
                entity['value'] = value

    def _sleep_us(self, us):
        if hasattr(time, 'sleep_us'):
            time.sleep_us(us)
        else:
            time.sleep(us / 1000000)

    def _ticks_ms(self):
        if hasattr(time, 'ticks_ms'):
            return time.ticks_ms()
        return int(time.time() * 1000)

    def _ticks_diff(self, end, start):
        if hasattr(time, 'ticks_diff'):
            return time.ticks_diff(end, start)
        return end - start

    def _log(self, message, logtype='INFO'):
        if self._log_callable:
            self._log_callable('Local', 'Grove-AC-Voltage', {'log': message}, logtype)
        else:
            log_output('Local', 'Grove-AC-Voltage', {'log': message}, logtype)
