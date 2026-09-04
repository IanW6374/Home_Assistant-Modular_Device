"""Bounded Device API inventory projections kept outside the runtime entry."""


class DeviceInventory:
    def __init__(self, sources):
        self.sources = dict(sources)

    def _value(self, name, default=None):
        value = self.sources.get(name, default)
        return value() if callable(value) else value

    def info(self):
        return {
            'device_name': self._value('device_name', ''),
            'device_id': self._value('device_id', ''),
            'application_version': self._value('application_version', ''),
            'firmware_version': self._value('firmware_version', ''),
            'micropython_version': self._value('micropython_version', ''),
            'uptime_s': self._value('uptime_s', 0),
            'board': self._value('board', ''),
            'drivers': self._value('drivers', []),
            'resources': self._value('resources', []),
            'runtime': self._value('runtime', {}),
            'boot': self._value('boot', {}),
            'capabilities': self._value('capabilities', {}),
            'interfaces': self.interfaces(),
            'features': self._value('features', {}),
            'release_sequence': self._value('release_sequence', 0),
            'firmware_release_sequence': self._value(
                'firmware_release_sequence', 0
            ),
            'release_qualification': self.qualification(),
            'qualification_observation': self._value(
                'qualification_observation', {}
            ),
        }

    def qualification(self):
        value = self._value('qualification', {}) or {}
        evidence = value.get('evidence') or {}
        return {
            'available': bool(value.get('available', False)),
            'summary': str(value.get('summary', 'Unavailable'))[:32],
            'promotion_ready': bool(evidence.get('promotion_ready', False)),
            'gates': [{
                'name': str(item.get('name', ''))[:32],
                'status': str(item.get('status', 'not-run'))[:16],
            } for item in list(evidence.get('gates', ()))[:16]],
        }

    def interfaces(self):
        api_enabled = self._value('api_enabled', False)
        return {
            'wifi': {
                'state': self._value('network_state', 'unknown'),
                'address': self._value('wifi_address', ''),
            },
            'mqtt': {'state': self._value('mqtt_state', 'unknown')},
            'device_api': {
                'state': 'online' if self._value('api_online', False) else (
                    'enabled' if api_enabled else 'disabled'
                ),
                'port': self._value('api_port', 8444),
            },
            'syslog': self._value('syslog', {}),
            'usb_ncm': self._value('usb_ncm', {}),
        }

    def configuration(self):
        return {
            'device_name': self._value('device_name', ''),
            'module_settings_file': self._value('module_settings_file', ''),
            'release_channel': self._value('release_channel', 'stable'),
            'device_api': {
                'enabled': self._value('api_enabled', False),
                'port': self._value('api_port', 8444),
            },
            'web_portal': {
                'enabled': self._value('portal_enabled', False),
                'port': self._value('portal_port', 8443),
                'transport': self._value('portal_transport', 'https'),
            },
        }

    def support(self):
        builder = self.sources['support_builder']
        return builder(
            self.info(), self._value('health'), self._value('modules', []), {
                'product': self._value('product_version', ''),
                'application': self._value('application_version', ''),
                'firmware': self._value('firmware_version', ''),
                'micropython': self._value('micropython_version', ''),
            }, self._value('fleet'), self._value('logs', [])
        )
