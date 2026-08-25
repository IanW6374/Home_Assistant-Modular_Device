"""Generated mapping used to import only configured IoTMD device drivers."""

DRIVER_MODULES = {
    'light:brightness': 'light',
    'light:onoff': 'light',
    'light:rgb': 'light',
    'sensor:EMS-Boiler': 'ems',
    'sensor:Grove-AC-Voltage': 'grove_ac_voltage',
    'sensor:MAX31865-PT1000': 'max31865_pt1000',
    'sensor:RS485-Modbus': 'rs485_modbus',
    'sensor:RS485-Modbus-Multiport': 'modbus_transport',
    'sensor:WHES': 'whes',
    'sensor:dht11': 'dht11',
    'sensor:hcsr04': 'hcsr04',
    'switch:dimmer': 'switch_dimmer',
    'switch:onoff': 'switch_onoff',
}

DRIVER_VERSIONS = {
    'dht11': 1,
    'ems': 4,
    'grove_ac_voltage': 1,
    'hcsr04': 1,
    'light': 1,
    'max31865_pt1000': 1,
    'modbus_transport': 1,
    'rs485_modbus': 1,
    'switch_dimmer': 1,
    'switch_onoff': 1,
    'whes': 1,
}
