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

DEVICE_INFO = {
    'mf': 'HAMD',
    'mdl': 'Home Assistant Modular Device',
    'hw': 'ESP32-S3-DevKitC-1-N8R8',
}
