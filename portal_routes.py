"""Versioned portal route registry and authorization metadata."""


ROLE_LEVELS = {'viewer': 10, 'operator': 20, 'administrator': 30}

ROUTES = {
    '/': ('viewer', 'status'),
    '/partials': ('viewer', 'status'),
    '/diagnostics': ('viewer', 'modules'),
    '/logging': ('viewer', 'maintenance'),
    '/logs': ('viewer', 'maintenance'),
    '/health-history': ('viewer', 'maintenance'),
    '/task-status': ('viewer', 'operations'),
    '/update-progress': ('viewer', 'operations'),
    '/updates': ('operator', 'maintenance'),
    '/check-release': ('operator', 'maintenance'),
    '/download-release': ('operator', 'maintenance'),
    '/update-upload': ('operator', 'maintenance'),
    '/firmware-upload': ('operator', 'maintenance'),
    '/universal-upload': ('operator', 'maintenance'),
    '/activate-update': ('operator', 'maintenance'),
    '/activate-firmware': ('operator', 'maintenance'),
    '/activate-universal': ('operator', 'maintenance'),
    '/rollback-application': ('operator', 'maintenance'),
    '/calibrate': ('operator', 'modules'),
    '/discover': ('operator', 'modules'),
    '/ems-debug': ('operator', 'modules'),
    '/trigger-discovery': ('operator', 'modules'),
    '/display-loglevel': ('operator', 'modules'),
    '/resumable-upload-begin': ('operator', 'updates'),
    '/resumable-upload-status': ('operator', 'updates'),
    '/resumable-upload-chunk': ('operator', 'updates'),
    '/resumable-upload-complete': ('operator', 'updates'),
    '/acme-settings': ('administrator', 'system'),
    '/certificate-upload': ('administrator', 'maintenance'),
    '/certificates': ('administrator', 'maintenance'),
    '/change-password': ('administrator', 'system'),
    '/configuration-backup': ('administrator', 'maintenance'),
    '/configuration-import-apply': ('administrator', 'maintenance'),
    '/configuration-import-preview': ('administrator', 'maintenance'),
    '/device-api': ('administrator', 'system'),
    '/download-configuration': ('administrator', 'maintenance'),
    '/download-diagnostics': ('administrator', 'maintenance'),
    '/download-logs': ('administrator', 'maintenance'),
    '/download-secure-configuration': ('administrator', 'maintenance'),
    '/factory-default': ('administrator', 'maintenance'),
    '/home-assistant': ('administrator', 'system'),
    '/logging-settings': ('administrator', 'system'),
    '/module-settings': ('administrator', 'system'),
    '/mqtt': ('administrator', 'system'),
    '/ntp-settings': ('administrator', 'system'),
    '/portal-settings': ('administrator', 'system'),
    '/reset-health-history': ('administrator', 'maintenance'),
    '/restart-device': ('administrator', 'operations'),
    '/api/restart-required': ('viewer', 'operations'),
    '/revoke-api-client': ('administrator', 'system'),
    '/secure-configuration-import-apply': ('administrator', 'maintenance'),
    '/secure-configuration-import-preview': ('administrator', 'maintenance'),
    '/set-loglevel': ('administrator', 'system'),
    '/settings': ('administrator', 'system'),
    '/update-preferences': ('administrator', 'maintenance'),
    '/user': ('administrator', 'system'),
    '/user/add': ('administrator', 'system'),
    '/user/update': ('administrator', 'system'),
    '/validate-certificates': ('administrator', 'maintenance'),
    '/validate-configuration': ('administrator', 'maintenance'),
    '/wifi-settings': ('administrator', 'system'),
}


def role_allows(role, required):
    return ROLE_LEVELS.get(str(role), -1) >= ROLE_LEVELS.get(str(required), 999)


def required_role(method, route):
    route = str(route).split('?', 1)[0]
    metadata = ROUTES.get(route)
    if metadata is None:
        return 'administrator'
    role = metadata[0]
    if role == 'viewer' and str(method).upper() != 'GET':
        return 'administrator'
    return role


def route_inventory():
    return [
        {'path': path, 'role': value[0], 'area': value[1]}
        for path, value in sorted(ROUTES.items())
    ]
