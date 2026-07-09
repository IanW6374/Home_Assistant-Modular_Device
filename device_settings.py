moduleSettingsFile = 'module_settings.json'
ca_cert_path = '/certs/home-ca.der'

ha_discovery = True
ha_devicename = 'WHES'

ntp_servers = (
    'pool.ntp.org',
    'time.google.com',
)

ha_device_info = {
    "mf": "Home",
    "mdl": "PicoW",
    "sw": "1.1",
    "hw": "1.0"
}

loglevel = 'INFO' # ERROR, INFO, or DEBUG. DEBUG includes MQTT topic/payload details and mqtt_as client debug messages.

web_portal_enabled = True
web_portal_https = False
web_portal_host = '0.0.0.0' # Default DHCP / Static IP - Set to bind to other IP address if you have multiple network interfaces
web_portal_port = None # Default HTTP:8080 / HTTPS:8443 - Set an integer to override.
web_portal_cert_path = '/certs/web.crt.der'
web_portal_key_path = '/certs/web.key.der'
web_portal_refresh_ms = 5000
web_log_lines = 100
web_log_line_max = 300

# Optional Waveshare Pico-OLED-1.3 local display.
#
# The display SPI and button pins match the Waveshare Pico-OLED-1.3 examples.
# Key0 is GP15 and Key1 is GP17.
local_display = {
    'enabled': True,
    'type': 'Waveshare-Pico-OLED-1.3',
    'width': 128,
    'height': 64,
    'spi': 1,
    'sck': 10,
    'mosi': 11,
    'cs': 9,
    'dc': 8,
    'rst': 12,
    'refresh_ms': 1000,
    'button_a': 15,
    'button_b': 17,
    'button_a_short': 'next_page',
    'button_a_long': 'refresh_discovery',
    'button_b_short': 'previous_page',
    'button_b_long': 'toggle_loglevel'
}

# Watchdog timeout in milliseconds.
#
# Recommended deployed value: 8000 (8 seconds). This is comfortably longer
# than the normal 5-6 second main loop heartbeat and gives WiFi/MQTT/NTP calls
# some room to pause without causing unnecessary resets. The Pico hardware
# limit is about 8388 ms. Set to 0 while developing over USB/REPL so the Pico
# does not reboot while paused at a prompt.
watchdog_timeout_ms = 8000
