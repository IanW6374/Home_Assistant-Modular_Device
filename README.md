# Home Assistant Modular Device

MicroPython firmware for a Raspberry Pi Pico W that exposes modular devices to
Home Assistant over MQTT. Devices are described in `device.json`, discovered at
boot, and handled by small driver modules in `device_modules/`.

The current configuration includes a WHES single-phase inverter driver over
RS485/Modbus RTU. The WHES driver reads a small set of inverter registers and
publishes Home Assistant-friendly power, battery, grid, and daily energy
entities.

## Features

- MQTT state publishing and Home Assistant MQTT discovery.
- Modular device drivers loaded from `device_modules/`.
- GPIO light and switch modules.
- Generic Pico 2-channel RS485 Modbus sensor module.
- WHES-specific RS485 module with calculated MQTT presentation entities.

## Repository Layout

```text
main.py                         Boot entry point, executes HA-Device.py
HA-Device.py                    WiFi, MQTT, discovery, and device orchestration
device.json                     Device and register configuration
device_settings.py              Local firmware settings
secrets.py                      WiFi and MQTT credentials, not suitable for commits
secrets.example.py              Template for local credentials
device_modules/                 Device driver modules
device_modules/whes.py          WHES inverter presentation/calculation driver
device_modules/pico_2ch_rs485.py Generic RS485 Modbus driver
tests/                          Host-side unit tests
lib/                            MicroPython support libraries
```

## Configuration

### `secrets.py`

Create/update `secrets.py` on the Pico with your WiFi and MQTT credentials:

```python
wifi_ssid = "your-ssid"
wifi_password = "your-wifi-password"

mqtt_server = "mqtt.example.local"
mqtt_username = "mqtt-user"
mqtt_password = "mqtt-password"
mqtt_ssl = True
```

### `device_settings.py`

`device_settings.py` selects the device config file, certificate path, Home
Assistant discovery behavior, and NTP servers:

```python
deviceConfigFile = "device.json"
ca_cert_path = "/certs/home-ca.der"
ha_discovery = True
ha_devicename = "Test1"
watchdog_timeout_ms = 0
```

If MQTT TLS is enabled, copy your CA certificate to the configured path on the
Pico. Set `watchdog_timeout_ms` to a positive value up to `8000` to enable the
Pico hardware watchdog after MQTT connects. Leave it as `0` while developing
over USB/REPL.

### `device.json`

Devices are declared in `device.json`. The current WHES config uses the `WHES`
sensor subclass and reads these Modbus registers:

| Key | Address | Type | Purpose |
| --- | ---: | --- | --- |
| `PPV1` | `36112` | `uint16` | PV string 1 power |
| `PPV2` | `36113` | `uint16` | PV string 2 power |
| `BatPower_BMS` | `36153` | `int32` | Signed battery power |
| `Power_Meter` | `36131` | `int32` | Signed grid meter power |
| `BatSOC` | `36155` | `uint16` | Battery state of charge |

The configured RS485 parameters are 115200 baud, 8 data bits, no parity, 1 stop
bit, slave address `1`, and Modbus function `4`.

`device_modules/validation.py` validates the loaded device config at boot and
logs issues such as missing fields, unsupported entity classes, duplicate keys,
invalid RS485 counts, and unsupported data types.

## WHES Home Assistant Entities

The WHES module reads the raw Modbus values above and publishes a cleaner
presentation payload to Home Assistant.

### Power and Battery Entities

| Published key | Unit | Source/calculation |
| --- | --- | --- |
| `PV_p` | W | `PPV1 + PPV2` |
| `battery_p` | W | `BatPower_BMS * -1` |
| `grid_p` | W | Raw `Power_Meter` |
| `home_p` | W | `PV_p + battery_p` |
| `battery_soc` | % | Raw `BatSOC` |

Sign conventions:

- Presented `battery_p > 0` means battery discharge.
- Presented `battery_p < 0` means battery charge.
- `Power_Meter > 0` means grid import.
- `Power_Meter < 0` means grid export.

### Daily Energy Entities

The WHES driver also integrates power into daily kWh totals and publishes them
as Home Assistant `energy` sensors with `state_class: total_increasing`.

| Published key | Unit | Based on |
| --- | --- | --- |
| `pv_e` | kWh | `PV_p` |
| `home_e` | kWh | `home_p` |
| `battery_charge_e` | kWh | Presented `battery_p` when negative |
| `battery_discharge_e` | kWh | Presented `battery_p` when positive |
| `grid_import_e` | kWh | `Power_Meter` when positive |
| `grid_export_e` | kWh | `Power_Meter` when negative |

Energy is accumulated from elapsed runtime between publishes:

```text
kWh += power_W * elapsed_ms / 3600000000
```

Published daily energy values are rounded to 4 decimal places. All daily energy
totals reset to `0` when the Pico local date changes at midnight. NTP sync is
enabled in `HA-Device.py`, so make sure the Pico can reach one of the configured
NTP servers.

## MQTT Topics

The Pico derives its MQTT device id from `machine.unique_id()`.

State is published to:

```text
homeassistant/sensor/<deviceid><uuid>/state
```

Home Assistant discovery config is published to:

```text
homeassistant/sensor/<deviceid><uuid>_<entity_index>/config
```

Devices that support command/set handling subscribe to:

```text
homeassistant/sensor/<deviceid><uuid>/set
```

The generic RS485 ad-hoc response topic is:

```text
homeassistant/sensor/<deviceid><uuid>/response
```

For the current WHES device UUID, `<uuid>` is `0001`.

## Running on the Pico

Copy the project files to the Pico filesystem, including:

- `main.py`
- `HA-Device.py`
- `device.json`
- `device_settings.py`
- `secrets.py`
- `device_modules/`
- `lib/`
- any configured TLS certificate files

On boot, `main.py` runs `HA-Device.py`, connects WiFi/MQTT, loads device modules,
subscribes to relevant topics, publishes Home Assistant discovery payloads, and
starts each sensor driver.

## Host-Side Tests

The `tests/` directory contains a small `unittest` suite for logic that can run
without Pico hardware:

```sh
python3 -m unittest discover -s tests
```

The tests cover WHES presentation calculations, rounded daily energy values,
Home Assistant topic helpers, and config validation.

## Adding a Device Module

Device modules live in `device_modules/` and are discovered automatically by
`device_modules/loader.py`. A module should provide:

- `DEVICE_TYPE`
- `supports(device)`
- `setup(device, index)`
- optionally `create_driver(device, device_char)`

Drivers normally inherit from `device_modules.base.DeviceDriver` or reuse an
existing driver, as `device_modules/whes.py` does with the generic RS485 driver.

Shared helpers in `device_modules/base.py` build Home Assistant MQTT topics and
common sensor discovery payloads.

## Notes

- The code targets MicroPython on Raspberry Pi Pico W.
- MQTT discovery uses the `homeassistant/` topic prefix.
- Generated bytecode/cache files are not needed on the Pico.
- Keep credentials and certificates out of public repositories.
- `.gitignore` excludes local secrets, certificates, bytecode, and macOS cache
  files.
