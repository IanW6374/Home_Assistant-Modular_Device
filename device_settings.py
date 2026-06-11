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