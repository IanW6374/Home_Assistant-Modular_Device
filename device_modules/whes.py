"""WHES inverter module.

Reads the small set of WHES Modbus values needed from RS485 and publishes a
Home Assistant presentation payload with calculated PV and home-load power.
"""

try:
    rs485_module = __import__('device_modules.Pico-2CH-RS485', None, None, ['setup', 'Pico2CHRS485Driver'])
except ImportError:
    rs485_module = __import__('Pico-2CH-RS485')

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
    {
        'key': 'PPV1',
        'class': 'power',
        'unit': 'W',
        'state_class': 'measurement',
        'source': True
    },
    {
        'key': 'PPV2',
        'class': 'power',
        'unit': 'W',
        'state_class': 'measurement',
        'source': True
    },
    {
        'key': 'PV_p',
        'class': 'power',
        'unit': 'W',
        'state_class': 'measurement'
    },
    {
        'key': 'BatPower_BMS',
        'class': 'power',
        'unit': 'W',
        'state_class': 'measurement',
        'source': True
    },
    {
        'key': 'battery_charge',
        'class': 'power',
        'unit': 'W',
        'state_class': 'measurement'
    },
    {
        'key': 'battery_discharge',
        'class': 'power',
        'unit': 'W',
        'state_class': 'measurement'
    },
    {
        'key': 'grid_p',
        'class': 'power',
        'unit': 'W',
        'state_class': 'measurement'
    },
    {
        'key': 'grid_import',
        'class': 'power',
        'unit': 'W',
        'state_class': 'measurement'
    },
    {
        'key': 'grid_export',
        'class': 'power',
        'unit': 'W',
        'state_class': 'measurement'
    },
    {
        'key': 'home_p',
        'class': 'power',
        'unit': 'W',
        'state_class': 'measurement'
    },
    {
        'key': 'battery_soc',
        'class': 'battery',
        'unit': '%',
        'state_class': 'measurement'
    },
    {
        'key': 'pv_energy',
        'class': 'energy',
        'unit': 'kWh',
        'state_class': 'total_increasing'
    },
    {
        'key': 'home_energy',
        'class': 'energy',
        'unit': 'kWh',
        'state_class': 'total_increasing'
    },
    {
        'key': 'battery_charge_energy',
        'class': 'energy',
        'unit': 'kWh',
        'state_class': 'total_increasing'
    },
    {
        'key': 'battery_discharge_energy',
        'class': 'energy',
        'unit': 'kWh',
        'state_class': 'total_increasing'
    },
    {
        'key': 'grid_import_energy',
        'class': 'energy',
        'unit': 'kWh',
        'state_class': 'total_increasing'
    },
    {
        'key': 'grid_export_energy',
        'class': 'energy',
        'unit': 'kWh',
        'state_class': 'total_increasing'
    }
)


ENERGY_SOURCES = (
    ('pv_energy', 'PV_p'),
    ('home_energy', 'home_p'),
    ('battery_charge_energy', 'battery_charge'),
    ('battery_discharge_energy', 'battery_discharge'),
    ('grid_import_energy', 'grid_import'),
    ('grid_export_energy', 'grid_export')
)


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

        for i, entity in enumerate(PRESENTATION_ENTITIES):
            key = entity['key']
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

        return payload_discovery, payload_entities

    def get_state_payload(self):
        values = {}
        for e in self.device['entities']:
            entity = self.device['entities'][str(e)]
            values[entity.get('key', entity['class'])] = entity.get('value', 0)

        ppv1 = self._number(values.get('PPV1', values.get('Ppv1', 0)))
        ppv2 = self._number(values.get('PPV2', values.get('Ppv2', 0)))
        bat_power_bms = self._number(values.get('BatPower_BMS', 0))
        grid_p = self._number(values.get('Power_Meter', 0))
        battery_soc = self._number(values.get('BatSOC', 0))

        values['PPV1'] = ppv1
        values['PPV2'] = ppv2
        values['BatPower_BMS'] = bat_power_bms
        values['PV_p'] = ppv1 + ppv2
        values['battery_charge'] = bat_power_bms if bat_power_bms > 0 else 0
        values['battery_discharge'] = -bat_power_bms if bat_power_bms < 0 else 0
        values['grid_p'] = grid_p
        values['grid_import'] = grid_p if grid_p > 0 else 0
        values['grid_export'] = -grid_p if grid_p < 0 else 0
        values['home_p'] = values['PV_p'] - bat_power_bms
        values['battery_soc'] = battery_soc

        for energy_key in self._energy_totals:
            values[energy_key] = self._energy_totals.get(energy_key, 0)

        payload = {}
        for entity in PRESENTATION_ENTITIES:
            payload[entity['key']] = values.get(entity['key'], 0)
        return payload

    def publish_state(self, publish_callable, deviceid):
        self._update_energy_totals()
        payload = self.get_state_payload()
        data = {
            'payload': payload,
            'topic': 'homeassistant/sensor/' + deviceid + self.device['uuid'] + '/state',
            'log': 'HA Update: ' + self.device['name']
        }
        publish_callable(data, 0, False)

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

    def _update_energy_totals(self):
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

        payload = self.get_state_payload()
        for energy_key, power_key in ENERGY_SOURCES:
            power = self._number(payload.get(power_key, 0))
            if power < 0:
                power = 0
            self._energy_totals[energy_key] += power * elapsed_ms / 3600000000
