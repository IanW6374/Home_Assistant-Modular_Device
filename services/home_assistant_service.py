"""Home Assistant discovery and availability publishing boundary."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

from device_modules.base import (
    mqtt_availability_topic, ha_config_topic, mqtt_command_topic,
    mqtt_module_topic, mqtt_state_topic,
    ha_unique_id,
    homeassistant_device_info, homeassistant_origin_info,
)


class HomeAssistantService:
    def __init__(
        self, device_id, device_name, devices, device_characters,
        device_type, publisher, logger, portal_url,
        module_health, system_enabled=False, system_discovery=None,
        system_state=None, maintenance_discovery=None,
    ):
        self.device_id = str(device_id)
        self.device_name = str(device_name)
        self.devices = devices
        self.device_characters = device_characters
        self.device_type = device_type
        self.publisher = publisher
        self.logger = logger
        self.portal_url = portal_url
        self.module_health = module_health
        self.system_enabled = bool(system_enabled)
        self.system_discovery = system_discovery
        self.system_state = system_state
        self.maintenance_discovery = maintenance_discovery
        self.last_discovery_count = 0

    def _operational_topics(self, payload, component, uuid):
        """Bind HA discovery to the configured platform-neutral MQTT topics."""
        payload = payload.copy()
        module_topic = mqtt_module_topic(component, self.device_id, uuid)
        replacements = {
            '~/state': mqtt_state_topic(component, self.device_id, uuid),
            '~/set': mqtt_command_topic(component, self.device_id, uuid),
        }
        for key in ('stat_t', 'state_topic', 'cmd_t', 'command_topic'):
            value = payload.get(key)
            if value in replacements:
                payload[key] = replacements[value]
            elif isinstance(value, str) and value.startswith('~/'):
                payload[key] = module_topic + value[1:]
        payload.pop('~', None)
        payload['availability_topic'] = mqtt_availability_topic(self.device_id)
        return payload

    def _character(self, uuid):
        return next(
            (item for item in self.device_characters() if item.get('uuid') == uuid),
            None,
        )

    def _module_health_discovery(self, device):
        payloads = {}
        for key in (
            'module_last_ok', 'module_last_error', 'module_last_read_ms',
            'module_last_publish_age_s', 'module_consecutive_errors',
        ):
            payloads[key] = {
                '~': mqtt_module_topic(
                    device['type']['class'], self.device_id, device['uuid']
                ),
                'stat_t': '~/state',
                'uniq_id': ha_unique_id(self.device_id, device['uuid'], key),
                'name': device['name'] + ' ' + key,
                'value_template': "{{ value_json[" + repr(key) + "] }}",
                'availability_topic': mqtt_availability_topic(self.device_id),
                'payload_available': 'online',
                'payload_not_available': 'offline',
                'entity_category': 'diagnostic',
                'en': False,
                'dev': homeassistant_device_info(
                    self.device_id, self.device_name, device.get('_portal_url')
                ),
                'o': homeassistant_origin_info(),
            }
        return payloads

    async def publish_discovery(self):
        count = 0
        device_info_added = False
        self.logger(
            'Local', 'HA Discovery', {'log': 'Publishing configuration'}, 'INFO'
        )
        for device in self.devices:
            descriptor = self.device_type(device)
            if (
                device.get('uuid') == '0000' or not descriptor or
                not descriptor.get('ha_discovery')
            ):
                continue
            discovery = {}
            entities = {}
            cleanup_topics = []
            character = self._character(device.get('uuid'))
            if character and character.get('driver'):
                try:
                    url = self.portal_url()
                    if url:
                        device['_portal_url'] = url
                    else:
                        device.pop('_portal_url', None)
                    driver = character['driver']
                    if hasattr(driver, 'prepare_discovery'):
                        await driver.prepare_discovery()
                    discovery, entities = driver.get_discovery_payloads(
                        self.device_id, self.device_name
                    )
                    health = self.module_health(driver)
                    if health:
                        entities.update(health)
                        discovery.update(self._module_health_discovery(device))
                        cleanup_topics.append(ha_config_topic(
                            device['type']['class'], self.device_id,
                            device['uuid'], 'module_last_publish_ms'
                        ))
                except Exception as exc:
                    self.logger(
                        'Local', 'HA Discovery',
                        {'log': device['name'] + ' - ' + str(exc)}, 'ERROR'
                    )
                    discovery, entities, cleanup_topics = {}, {}, []
            else:
                self.logger(
                    'Local', 'HA Discovery',
                    {'log': device['name'] + ' - no driver available for discovery'},
                    'ERROR',
                )
            if not device_info_added and discovery:
                first = next(iter(discovery))
                if 'dev' not in discovery[first]:
                    discovery[first]['dev'] = homeassistant_device_info(
                        self.device_id, self.device_name,
                        device.get('_portal_url')
                    )
                device_info_added = True
            for topic in cleanup_topics:
                await self.publisher({
                    'payload': None, 'topic': topic,
                    'log': 'HA Discovery cleanup: ' + device['name'] + ' - ' + topic,
                }, 0, False, True)
            device_count = 0
            for entity_id in discovery:
                payload = discovery[entity_id].copy()
                topic = payload.pop('_topic', None)
                component = payload.pop('_component', device['type']['class'])
                payload = self._operational_topics(
                    payload, component, device['uuid']
                )
                topic = topic or ha_config_topic(
                    component, self.device_id, device['uuid'], entity_id
                )
                await self.publisher({
                    'payload': payload, 'topic': topic,
                    'log': 'HA Discovery entity: ' + device['name'] + ' ' +
                    str(entity_id),
                }, 0, False, True)
                count += 1
                device_count += 1
            if device_count:
                self.logger(
                    'Local', 'HA Discovery',
                    {'log': device['name'] + ' - ' + str(device_count) +
                     ' config payloads'}, 'INFO'
                )
            await asyncio.sleep(1)
            await self.publisher({
                'payload': entities,
                'topic': mqtt_state_topic(
                    device['type']['class'], self.device_id, device['uuid']
                ),
                'log': 'MQTT State: ' + device['name'],
            }, 0, False)

        if self.system_enabled:
            system_count = 0
            for key, payload in (self.system_discovery() or {}).items():
                payload = self._operational_topics(payload, 'sensor', 'sys')
                await self.publisher({
                    'payload': payload,
                    'topic': ha_config_topic('sensor', self.device_id, 'sys', key),
                    'log': 'HA Discovery entity: system diagnostics ' + str(key),
                }, 0, False, True)
                count += 1
                system_count += 1
            await self.publisher({
                'payload': self.system_state(),
                'topic': mqtt_state_topic('sensor', self.device_id, 'sys'),
                'log': 'MQTT State: system diagnostics',
            }, 0, False)
            for key, payload in (self.maintenance_discovery() or {}).items():
                payload = self._operational_topics(payload, 'button', 'maint')
                await self.publisher({
                    'payload': payload,
                    'topic': ha_config_topic('button', self.device_id, 'maint', key),
                    'log': 'HA Discovery entity: maintenance ' + str(key),
                }, 0, False, True)
                count += 1
                system_count += 1
            self.logger(
                'Local', 'HA Discovery',
                {'log': 'system diagnostics - ' + str(system_count) +
                 ' config payloads'}, 'INFO'
            )
        self.last_discovery_count = count
        self.logger(
            'Local', 'HA Discovery',
            {'log': 'Completed with ' + str(count) + ' config payloads'}, 'INFO'
        )
        return count

    async def publish_availability(self, state):
        await self.publisher({
            'payload': state,
            'topic': mqtt_availability_topic(self.device_id),
            'log': 'Availability: ' + state,
        }, 0, False, True)
