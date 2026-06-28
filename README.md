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

web_portal_token = "replace-with-a-long-random-url-safe-token"
```

### `device_settings.py`

`device_settings.py` selects the device config file, certificate path, Home
Assistant discovery behavior, and NTP servers:

```python
deviceConfigFile = "device.json"
ca_cert_path = "/certs/home-ca.der"
ha_discovery = True
ha_devicename = "Test1"
ntp_servers = (
    "pool.ntp.org",
    "time.google.com",
)
watchdog_timeout_ms = 0
web_portal_enabled = False
web_portal_https = False
web_portal_port = None
web_portal_cert_path = "/certs/web.crt.der"
web_portal_key_path = "/certs/web.key.der"
web_portal_refresh_ms = 5000
```

If MQTT TLS is enabled, copy your CA certificate to the configured path on the
Pico. Set `watchdog_timeout_ms` to a positive value up to `8000` to enable the
Pico hardware watchdog after MQTT connects; the RP2040 hardware limit is about
`8388` ms. Leave it as `0` while developing over USB/REPL.

### Web Log Portal

The optional web portal exposes recent firmware logs and lets you change the
runtime debug level remotely. It is disabled by default. To enable it, set
`web_portal_enabled = True` and add `web_portal_token` to `secrets.py`. The
portal binds to all network interfaces by default and logs the actual WiFi IP
address after startup.

Open the portal with:

```text
http://<pico-ip>:8080/?token=<web_portal_token>
```

When `web_portal_port = None`, the firmware uses `8080` for HTTP and `8443`
for HTTPS. Set `web_portal_port` to an integer only when you want a custom
port.

The portal accepts `ERROR`, `INFO`, and `DEBUG` log levels. Changes are runtime
only and are not written back to `device_settings.py`, so rebooting restores the
configured default. The log pane refreshes automatically using
`web_portal_refresh_ms` and remains scrollable so earlier buffered log events
can be reviewed.

The portal defaults to HTTP because server-side TLS exhausted heap during Pico W
testing. If HTTPS is required on Pico W hardware, terminate TLS on a reverse
proxy such as Home Assistant, Caddy, or nginx and proxy to the Pico's HTTP
portal on the trusted LAN.

#### Pico 2 W HTTPS

HTTPS has been tested successfully on Raspberry Pi Pico 2 W. Enable it in
`device_settings.py`:

```python
web_portal_https = True
web_portal_port = None
web_portal_cert_path = "/certs/web.crt.der"
web_portal_key_path = "/certs/web.key.der"
```

Create a small self-signed certificate and convert the files to DER:

```sh
openssl genrsa -traditional -out web.key 1024
openssl req -new -x509 -key web.key -out web.crt -days 365 \
  -subj "/CN=pico-web-portal"
openssl rsa -in web.key -outform DER -out web.key.der
openssl x509 -in web.crt -outform DER -out web.crt.der
```

Copy `web.key.der` and `web.crt.der` to `/certs/` on the Pico. Pico W testing
ran out of heap during the TLS handshake; Pico 2 W has enough headroom in the
tested setup. If another MicroPython build logs `OSError: [Errno 12] ENOMEM`
when a browser connects, use HTTP mode or terminate HTTPS on a reverse proxy.

### `device.json`

Devices are declared in `device.json`. The current WHES config uses the `WHES`
sensor subclass and reads these Modbus registers:

The WHES serial number is read from Modbus and used to prefix Home Assistant
entity names instead of `WHES`.

| Key | Address | Type | Purpose |
| --- | ---: | --- | --- |
| `SerialNumber` | `36010` | `ascii`, count `10` | Inverter serial number |
| `PPV1` | `36112` | `uint16` | PV string 1 power |
| `PPV2` | `36113` | `uint16` | PV string 2 power |
| `BatPower_BMS` | `36153` | `int32` | Signed battery power |
| `Power_Meter` | `36131` | `int32` | Signed grid meter power |
| `BatSOC` | `36155` | `uint16` | Battery state of charge |
| `battery_min_cap` | `60009` | `uint16` | Minimum battery capacity |

The configured RS485 parameters are 115200 baud, 8 data bits, no parity, 1 stop
bit, slave address `1`, and Modbus function `4`.

`device_modules/validation.py` validates the loaded device config at boot and
logs issues such as missing fields, unsupported entity classes, duplicate keys,
invalid RS485 counts, and unsupported data types.

## WHES Home Assistant Entities

The WHES module reads the raw Modbus values above and publishes a cleaner
presentation payload to Home Assistant.

It also publishes a `serial_number` diagnostic sensor. The serial number is sent
in Home Assistant MQTT device metadata as `sn`. If the web log portal is enabled,
the firmware sends its runtime portal URL as the Home Assistant device
configuration URL.

### Power and Battery Entities

| Published key | Unit | Source/calculation |
| --- | --- | --- |
| `PV_p` | W | `PPV1 + PPV2` |
| `battery_p` | W | `BatPower_BMS * -1` |
| `grid_p` | W | Raw `Power_Meter` |
| `home_p` | W | `PV_p + battery_p + grid_p` |
| `battery_soc` | % | Raw `BatSOC` |
| `battery_min_cap` | % | Raw `battery_min_cap` |

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

RS485 modules accept ad-hoc Modbus read and write requests on the `/set` topic.
Read requests remain backwards-compatible, so `operation` is optional when no
`value` or `values` field is present:

```json
{
  "request_id": "read-battery-soc",
  "operation": "read",
  "port": "ch0",
  "slave": 1,
  "function": 4,
  "address": 36155,
  "count": 1,
  "data_type": "uint16"
}
```

Write requests use Modbus function `6` for a single register by default, or
function `0x10`/`16` for multiple registers. The WHES inverter accepts function
`x10`, and payloads may use `16`, `"16"`, `"0x10"`, or `"x10"`:

```json
{
  "request_id": "set-min-battery",
  "operation": "write",
  "port": "ch0",
  "slave": 1,
  "function": "x10",
  "address": 60009,
  "values": [20],
  "data_type": "uint16"
}
```

Responses are published to `/response` with `ok`, `operation`, the request
metadata, and either `value`/`raw` or `error`.

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

## V1 Deployment Checklist

- Set `watchdog_timeout_ms = 0` while flashing or debugging over USB/REPL.
- Set `watchdog_timeout_ms = 8000` for deployment.
- Let the device connect to MQTT and publish Home Assistant discovery once.
- Confirm Home Assistant shows these WHES entities:
  `serial_number`, `PV_p`, `battery_p`, `grid_p`, `home_p`, `battery_soc`,
  `pv_e`, `home_e`, `battery_charge_e`, `battery_discharge_e`,
  `grid_import_e`, and `grid_export_e`.

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
