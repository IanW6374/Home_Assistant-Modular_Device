deviceConfigFile = 'device.json'
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

mqtt_debug = False # Set to True to print MQTT messages to the console e.g. WiFi connection status, MQTT connection status, MQTT messages received etc.

web_portal_enabled = True
web_portal_https = False
web_portal_host = '0.0.0.0'
web_portal_port = None # Use 8080 for HTTP or 8443 for HTTPS. Set an integer to override.
web_portal_cert_path = '/certs/web.crt.der'
web_portal_key_path = '/certs/web.key.der'
web_portal_refresh_ms = 5000
web_log_lines = 100
web_log_line_max = 300

# Watchdog timeout in milliseconds.
#
# Recommended deployed value: 8000 (8 seconds). This is comfortably longer
# than the normal 5-6 second main loop heartbeat and gives WiFi/MQTT/NTP calls
# some room to pause without causing unnecessary resets. The Pico hardware
# limit is about 8388 ms. Set to 0 while developing over USB/REPL so the Pico
# does not reboot while paused at a prompt.
watchdog_timeout_ms = 8000
