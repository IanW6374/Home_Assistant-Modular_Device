"""WHES inverter module.

Reads the small set of WHES Modbus values needed from RS485 and publishes a
Home Assistant presentation payload with calculated PV and home-load power.
"""

try:
    rs485_module = __import__('device_modules.Pico-2CH-RS485', None, None, ['setup', 'Pico2CHRS485Driver'])
except ImportError:
    rs485_module = __import__('Pico-2CH-RS485')


DEVICE_TYPE = {
    'class': 'sensor',
    'subclass': {
        'WHES': {
            'entities': {
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
        'key': 'Power_PV_Meter',
        'class': 'power',
        'unit': 'W',
        'state_class': 'measurement',
        'source': True
    },
    {
        'key': 'home_p',
        'class': 'power',
        'unit': 'W',
        'state_class': 'measurement'
    }
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
        power_pv_meter = self._number(values.get('Power_PV_Meter', 0))

        values['PPV1'] = ppv1
        values['PPV2'] = ppv2
        values['BatPower_BMS'] = bat_power_bms
        values['Power_PV_Meter'] = power_pv_meter
        values['PV_p'] = ppv1 + ppv2
        values['home_p'] = values['PV_p'] - bat_power_bms - power_pv_meter

        payload = {}
        for entity in PRESENTATION_ENTITIES:
            payload[entity['key']] = values.get(entity['key'], 0)
        return payload

    def publish_state(self, publish_callable, deviceid):
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
