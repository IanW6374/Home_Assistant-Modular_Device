"""Central, capability-aware feature policy for the IoT-MD runtime."""


FEATURES = {
    'transport_independent_api': {
        'default': True,
    },
    'split_api_payloads': {
        'default': True,
    },
    'hardware_resource_manager': {
        'default': True,
    },
    'usb_ncm': {
        'default': False,
        'capability': 'usb_ncm',
        'channels': ('beta', 'development'),
    },
    'tls_session_resumption': {
        'default': False,
        'capability': 'tls_session_resumption',
        'channels': ('beta', 'development'),
    },
}


class FeatureFlags:
    """Resolve signed policy against build, channel, and runtime capability."""

    def __init__(self, policy=None, capabilities=None, channel='stable',
                 build_features=None):
        self.policy = dict(policy or {})
        self.capabilities = dict((capabilities or {}).get('features', {}))
        self.channel = str(channel or 'stable').lower()
        self.build_features = dict(build_features or {})

    def state(self, name):
        definition = FEATURES.get(name)
        if definition is None:
            return {
                'requested': False, 'enabled': False,
                'reason': 'unknown feature flag',
            }
        requested = self.policy.get(name, definition.get('default', False)) is True
        if not requested:
            return {
                'requested': False, 'enabled': False,
                'reason': 'disabled by signed application policy',
            }
        if self.build_features.get(name, True) is not True:
            return {
                'requested': True, 'enabled': False,
                'reason': 'not included in this firmware build',
            }
        channels = definition.get('channels')
        if channels and self.channel not in channels:
            return {
                'requested': True, 'enabled': False,
                'reason': 'not enabled on the ' + self.channel + ' channel',
            }
        capability = definition.get('capability')
        if capability and self.capabilities.get(capability) is not True:
            return {
                'requested': True, 'enabled': False,
                'reason': 'runtime capability ' + capability + ' is unavailable',
            }
        return {'requested': True, 'enabled': True, 'reason': 'enabled'}

    def enabled(self, name):
        return self.state(name)['enabled']

    def snapshot(self):
        return {
            'channel': self.channel,
            'features': {
                name: self.state(name) for name in sorted(FEATURES)
            },
        }
