"""Certificate portal actions kept outside the runtime composition root."""

import certificate_enrollment_service
import certificate_trust
import device_config
import fleet_management

_dependencies = ()


def configure(*dependencies):
    global _dependencies
    _dependencies = dependencies


def _paths():
    return {
        'trust-ca': device_config.MQTT_CA_PATH,
        'portal-cert': device_config.WEB_PORTAL_CERT_PATH,
        'portal-key': device_config.WEB_PORTAL_KEY_PATH,
        'api-server-cert': device_config.API_SERVER_CERT_PATH,
        'api-server-key': device_config.API_SERVER_KEY_PATH,
    }


def apply(action, params):
    if not _dependencies:
        raise RuntimeError('certificate portal actions are not configured')
    api_ca_store, reload_portal, reload_identities, reload_api, mark_restart = _dependencies
    if action == 'remove-certificate-trust':
        message, api_changed = certificate_trust.remove(
            params.get('kind'), params.get('fingerprint'), api_ca_store, {
                'mqtt-ca': device_config.MQTT_CA_PATH,
                'release-ca': device_config.RELEASE_CA_PATH,
                'syslog-ca': device_config.SYSLOG_CA_PATH,
                'management-suite-key': fleet_management.FLEET_VERIFICATION_KEY_PATH,
            })
        if api_changed:
            reload_api()
            return message + '; Device API trust is reloading'
        mark_restart('Certificate trust removed')
        return message + '; restart the device to reload client connections'
    if action == 'certificate-method':
        return certificate_enrollment_service.change(
            params.get('method'), params, _paths(), reload_portal,
            reload_identities
        )
    return None
