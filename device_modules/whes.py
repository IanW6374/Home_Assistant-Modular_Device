"""WHES inverter module.

Reads the small set of WHES Modbus values needed from RS485 and publishes a
Home Assistant presentation payload with calculated PV and home-load power.
"""

try:
    from . import pico_2ch_rs485 as rs485_module
    from .base import ha_state_topic
    from .base import sensor_discovery_payload
except ImportError:
    import pico_2ch_rs485 as rs485_module
    from base import ha_state_topic
    from base import sensor_discovery_payload

import time


DEVICE_TYPE = {
    'class': 'sensor',
    'subclass': {
        'WHES': {
            'entities': {
                'battery',
                'power'
            }
        }
    },
    'ha_discovery': True,
    'ha_subscribe': True,
    'local_init': False
}


PRESENTATION_ENTITIES = (
    ('PV_p', 'power', 'W', 'measurement'),
    ('battery_p', 'power', 'W', 'measurement'),
    ('grid_p', 'power', 'W', 'measurement'),
    ('home_p', 'power', 'W', 'measurement'),
    ('battery_soc', 'battery', '%', 'measurement'),
    ('pv_e', 'energy', 'kWh', 'total_increasing'),
    ('home_e', 'energy', 'kWh', 'total_increasing'),
    ('battery_charge_e', 'energy', 'kWh', 'total_increasing'),
    ('battery_discharge_e', 'energy', 'kWh', 'total_increasing'),
    ('grid_import_e', 'energy', 'kWh', 'total_increasing'),
    ('grid_export_e', 'energy', 'kWh', 'total_increasing')
)


PRESENTATION_KEYS = tuple(entity[0] for entity in PRESENTATION_ENTITIES)

PRESENTATION_ENTITY_INDEXES = {
    key: index for index, (key, _, _, _) in enumerate(PRESENTATION_ENTITIES)
}

ENERGY_SOURCES = (
    ('pv_e', 'PV_p'),
    ('home_e', 'home_p'),
    ('battery_charge_e', 'battery_charge_p'),
    ('battery_discharge_e', 'battery_discharge_p'),
    ('grid_import_e', 'grid_import_p'),
    ('grid_export_e', 'grid_export_p')
)


RAW_KEYS = {
    'battery_p': 'BatPower_BMS',
    'battery_soc': 'BatSOC',
    'grid_p': 'Power_Meter',
    'ppv1': 'PPV1',
    'ppv2': 'PPV2'
}


ENERGY_PRECISION = 4


def supports(device):
    return (
        device['type']['class'] == 'sensor' and
        device['type']['subclass'] == 'WHES'
    )


def setup(device, index):
    return rs485_module.setup(device, index)


def create_driver(device, device_char):
    return WHESDriver(device, device_char)


class WHESDriver(rs485_module.Pico2CHRS485Driver):
    def __init__(self, device, device_char):
        super().__init__(device, device_char)
        self._energy_totals = {}
        for energy_key, _ in ENERGY_SOURCES:
            self._energy_totals[energy_key] = 0
        self._energy_ticks = None
        self._energy_day = None

    def get_discovery_payloads(self, deviceid, ha_devicename):
        payload_discovery = {}
        payload_entities = self.get_state_payload()

        for entity in PRESENTATION_ENTITIES:
            key, entity_class, unit, state_class = entity
            index = PRESENTATION_ENTITY_INDEXES[key]
            payload_discovery[index] = sensor_discovery_payload(
                self.device,
                {
                    'class': entity_class,
                    'unit': unit,
                    'state_class': state_class
                },
                key,
                index,
                deviceid,
                ha_devicename
            )

        return payload_discovery, payload_entities

    def get_state_payload(self):
        values = self._calculated_values()
        self._add_energy_values(values)
        return self._presentation_payload(values)

    def publish_state(self, publish_callable, deviceid):
        values = self._calculated_values()
        self._update_energy_totals(values)
        self._add_energy_values(values)
        payload = self._presentation_payload(values)
        data = {
            'payload': payload,
            'topic': ha_state_topic('sensor', deviceid, self.device['uuid']),
            'log': 'HA Update: ' + self.device['name']
        }
        publish_callable(data, 0, False)

    def _source_values(self):
        values = {}
        for e in self.device['entities']:
            entity = self.device['entities'][str(e)]
            values[entity.get('key', entity['class'])] = entity.get('value', 0)
        return values

    def _calculated_values(self):
        source = self._source_values()
        ppv1 = self._number(source.get(RAW_KEYS['ppv1'], source.get('Ppv1', 0)))
        ppv2 = self._number(source.get(RAW_KEYS['ppv2'], source.get('Ppv2', 0)))
        battery_p = self._number(source.get(RAW_KEYS['battery_p'], 0)) * -1
        grid_p = self._number(source.get(RAW_KEYS['grid_p'], 0))

        values = {
            'PV_p': ppv1 + ppv2,
            'battery_p': battery_p,
            'battery_charge_p': -battery_p if battery_p < 0 else 0,
            'battery_discharge_p': battery_p if battery_p > 0 else 0,
            'grid_p': grid_p,
            'grid_import_p': grid_p if grid_p > 0 else 0,
            'grid_export_p': -grid_p if grid_p < 0 else 0,
            'battery_soc': self._number(source.get(RAW_KEYS['battery_soc'], 0))
        }
        values['home_p'] = values['PV_p'] + battery_p
        return values

    def _add_energy_values(self, values):
        for energy_key in self._energy_totals:
            values[energy_key] = round(
                self._energy_totals.get(energy_key, 0),
                ENERGY_PRECISION
            )

    def _presentation_payload(self, values):
        payload = {}
        for key in PRESENTATION_KEYS:
            payload[key] = values.get(key, 0)
        return payload

    def _number(self, value):
        try:
            return float(value)
        except Exception:
            return 0

    def _current_day(self):
        now = time.localtime()
        return (now[0], now[1], now[2])

    def _ticks_ms(self):
        if hasattr(time, 'ticks_ms'):
            return time.ticks_ms()
        return int(time.time() * 1000)

    def _ticks_diff(self, end, start):
        if hasattr(time, 'ticks_diff'):
            return time.ticks_diff(end, start)
        return end - start

    def _update_energy_totals(self, values):
        current_day = self._current_day()
        current_ticks = self._ticks_ms()

        if self._energy_day != current_day:
            for energy_key in self._energy_totals:
                self._energy_totals[energy_key] = 0
            self._energy_day = current_day
            self._energy_ticks = current_ticks
            return

        if self._energy_ticks is None:
            self._energy_ticks = current_ticks
            return

        elapsed_ms = self._ticks_diff(current_ticks, self._energy_ticks)
        self._energy_ticks = current_ticks
        if elapsed_ms <= 0:
            return

        for energy_key, power_key in ENERGY_SOURCES:
            power = self._number(values.get(power_key, 0))
            if power < 0:
                power = 0
            self._energy_totals[energy_key] += power * elapsed_ms / 3600000000
