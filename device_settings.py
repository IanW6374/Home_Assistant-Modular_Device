deviceConfigFile = 'device.json'
ca_cert_path = '/certs/home-ca.der'

ha_discovery = True
ha_devicename = 'Test1'

ntp_servers = (
    'pool.ntp.org',
    'time.google.com',
)

ha_device_info = {
    "mf": "Home",
    "mdl": "PicoW",
    "sw": "1.0",
    "hw": "1.0"
}

mqtt_debug = False # Set to True to print MQTT messages to the console e.g. WiFi connection status, MQTT connection status, MQTT messages received etc.

# Watchdog timeout in milliseconds.
#
# Recommended deployed value: 30000 (30 seconds). This is comfortably longer
# than the normal 5-6 second main loop heartbeat and gives WiFi/MQTT/NTP calls
# some room to pause without causing unnecessary resets. Set to 0 while
# developing over USB/REPL so the Pico does not reboot while paused at a prompt.
watchdog_timeout_ms = 0
