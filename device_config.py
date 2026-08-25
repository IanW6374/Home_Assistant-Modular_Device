"""Immutable device and security policy frozen into the signed core."""

MODULE_SETTINGS_FILE = 'module_settings.json'

WATCHDOG_TIMEOUT_MS = 60000
WIFI_RECOVERY_ENABLED = True
WIFI_RECOVERY_TIMEOUT_S = 900
NETWORK_TRIAL_TIMEOUT_S = 180
STATUS_LED_PIN = 38
STATUS_LED_TYPE = 'neopixel'

WEB_PORTAL_HOST = '0.0.0.0'
WEB_PORTAL_PORT = None
WEB_PORTAL_CERT_PATH = '/certs/web.crt.der'
WEB_PORTAL_KEY_PATH = '/certs/web.key.der'
WEB_PORTAL_UPDATE_MAX_BYTES = 4 * 1024 * 1024
WEB_PORTAL_FIRMWARE_UPDATE_MAX_BYTES = 4 * 1024 * 1024
WEB_PORTAL_ALLOW_PROTECTED_UPDATES = True

TRUST_CA_PATH = '/certs/trust/home-rca-root.der'
MQTT_CA_PATH = '/certs/trust/mqtt-ca.der'
RELEASE_CA_PATH = '/certs/trust/release-ca.der'
API_CLIENT_CA_PATH = '/certs/trust/api-client-ca.der'
API_CLIENT_CA_DIRECTORY = '/certs/trust/api-clients'
API_CLIENT_REGISTRY_PATH = '/certs/api-clients.json'
SYSLOG_CA_PATH = '/certs/trust/syslog-ca.der'
DEVICE_API_HOST = '0.0.0.0'
DEVICE_API_PORT = 8444
DEVICE_API_MAX_BODY_BYTES = 8192

DEVICE_INFO = {
    'mf': 'IoTMD',
    'mdl': 'IoT Modular Device',
    'hw': 'ESP32-S3-DevKitC-1-N8R8',
}
