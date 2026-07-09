# Home Assistant Modular Device

MicroPython firmware for a Raspberry Pi Pico W that exposes modular devices to
Home Assistant over MQTT. Modules are described in `module_settings.json`,
discovered at boot, and handled by small driver modules in `device_modules/`.

The current checked-in `module_settings.json` includes a WHES single-phase inverter
driver over RS485/Modbus RTU. Additional example configs show standalone Pico
devices for EMS boiler monitoring, PT1000 temperature sensing, and AC voltage
presence/measurement.

## Features

- MQTT state publishing and Home Assistant MQTT discovery.
- Modular device drivers loaded from `device_modules/`.
- GPIO light and switch modules.
- Generic Pico 2-channel RS485 Modbus sensor module.
- WHES-specific RS485 module with calculated MQTT presentation entities.
- Read-only Bosch/Worcester EMS boiler monitor over an EMS-to-TTL interface.
- MAX31865/PT1000 RTD temperature sensor over SPI.
- Grove MCP6002 AC voltage sensor over ADC, with optional threshold binary
  sensor.
- Optional local Waveshare Pico-OLED-1.3 status display.

## Repository Layout

```text
main.py                         Boot entry point, executes HA-Device.py
HA-Device.py                    WiFi, MQTT, discovery, and device orchestration
module_settings.json            Module and register configuration
device_settings.py              Local firmware settings
local_display.py                Optional SH1107 OLED status display service
module_settings.ems.example.json EMS boiler example configuration
module_settings.max31865_pt1000.example.json PT1000/MAX31865 example configuration
module_settings.grove_ac_voltage.example.json Grove AC voltage example configuration
module_settings.dual_pt1000_voltage_display.example.json Combined PT1000/voltage/display example
secrets.py                      WiFi and MQTT credentials, not suitable for commits
secrets.example.py              Template for local credentials
device_modules/                 Device driver modules
device_modules/whes.py          WHES inverter presentation/calculation driver
device_modules/pico_2ch_rs485.py Generic RS485 Modbus driver
device_modules/ems.py           Read-only EMS boiler monitor
device_modules/max31865_pt1000.py MAX31865 PT1000 RTD driver
device_modules/grove_ac_voltage.py Grove AC voltage ADC driver
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

`device_settings.py` selects the module settings file, certificate path, Home
Assistant discovery behavior, and NTP servers:

```python
moduleSettingsFile = "module_settings.json"
ca_cert_path = "/certs/home-ca.der"
ha_discovery = True
ha_devicename = "Test1"
ntp_servers = (
    "pool.ntp.org",
    "time.google.com",
)
loglevel = "INFO"
watchdog_timeout_ms = 0
web_portal_enabled = False
web_portal_https = False
web_portal_port = None
web_portal_cert_path = "/certs/web.crt.der"
web_portal_key_path = "/certs/web.key.der"
web_portal_refresh_ms = 5000
local_display = {
    "enabled": False,
    "type": "Waveshare-Pico-OLED-1.3",
    "width": 128,
    "height": 64,
    "spi": 1,
    "sck": 10,
    "mosi": 11,
    "cs": 9,
    "dc": 8,
    "rst": 12,
    "refresh_ms": 1000,
    "button_a": 15,
    "button_b": 17,
    "button_a_short": "next_page",
    "button_a_long": "refresh_discovery",
    "button_b_short": "previous_page",
    "button_b_long": "toggle_loglevel",
}
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
configured default. `DEBUG` also enables MQTT topic/payload logging and
`mqtt_as` client debug output. The log pane refreshes automatically using
`web_portal_refresh_ms` and remains scrollable so earlier buffered log events can
be reviewed.

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

### Local OLED Display

`local_display.py` adds an optional status display for Waveshare Pico-OLED-1.3
style SH1107 modules. It is disabled by default; enable it in
`device_settings.py` by setting:

```python
local_display["enabled"] = True
```

The default SPI and button pins match the Waveshare Pico-OLED-1.3 examples:

| Signal | Pico GPIO |
| --- | ---: |
| SCK | GP10 |
| MOSI | GP11 |
| CS | GP9 |
| DC | GP8 |
| RST | GP12 |
| Key0 / button A | GP15 |
| Key1 / button B | GP17 |

When enabled, the display shows WiFi/MQTT status, the active config file, log
level, web portal state, recent error alerts, and current device payload values.
Short and long presses can page through screens, request Home Assistant
discovery, or toggle the runtime log level.

### Module Settings Files

`device_settings.py` points at the active module settings file through
`moduleSettingsFile`. The default remains:

```python
moduleSettingsFile = "module_settings.json"
```

The repo includes separate example configs for standalone Pico devices:

| File | Sensor subclass | Purpose |
| --- | --- | --- |
| `module_settings.json` | `WHES` | Current WHES inverter RS485/Modbus setup |
| `module_settings.ems.example.json` | `EMS-Boiler` | Worcester/Bosch EMS boiler broadcast monitor |
| `module_settings.max31865_pt1000.example.json` | `MAX31865-PT1000` | PT1000 RTD probe through a MAX31865 amplifier |
| `module_settings.grove_ac_voltage.example.json` | `Grove-AC-Voltage` | Grove MCP6002 AC voltage measurement and optional AC-present binary sensor |
| `module_settings.dual_pt1000_voltage_display.example.json` | `MAX31865-PT1000`, `Grove-AC-Voltage` | Two PT1000 probes plus Grove AC voltage, intended for use with the local OLED display |

Copy one of the example files or point `moduleSettingsFile` at it on the target
Pico. Each example assumes a dedicated Pico for that hardware role.

For the combined PT1000/voltage/display example, set:

```python
moduleSettingsFile = "module_settings.dual_pt1000_voltage_display.example.json"
local_display["enabled"] = True
```

It allocates GPIOs this way:

| Hardware | Pico GPIOs |
| --- | --- |
| MAX31865 flow probe | SPI0 SCK GP2, MOSI GP3, MISO GP4, CS GP5 |
| MAX31865 return probe | SPI0 SCK GP2, MOSI GP3, MISO GP4, CS GP6 |
| Grove AC voltage sensor | ADC0 GP26 |
| Waveshare Pico-OLED-1.3 display | SPI1 SCK GP10, MOSI GP11, CS GP9, DC GP8, RST GP12 |
| Display Key0 / Key1 | GP15 / GP17 |

### WHES `module_settings.json`

Modules are declared in `module_settings.json`. The current WHES config uses
the `WHES` sensor subclass and reads these Modbus registers:

The WHES serial number is read from Modbus and used to prefix Home Assistant
entity names instead of `WHES`.

| Key | Address | Type | Purpose |
| --- | ---: | --- | --- |
| `DeviceType` | `36001` | `uint16` | Device type |
| `Manufacturer` | `36002` | `ascii`, count `8` | Manufacturer |
| `SerialNumber_INV` | `36010` | `ascii`, count `10` | Inverter serial number |
| `DSP1_ver` | `36020` | `ascii`, count `8` | DSP1 firmware version |
| `DSP2_ver` | `36028` | `ascii`, count `8` | DSP2 firmware version |
| `EMS_ver` | `36036` | `ascii`, count `8` | EMS firmware version |
| `BMS_ver` | `36044` | `ascii`, count `16` | BMS firmware version |
| `Hardware_Version` | `36060` | `ascii`, count `8` | Hardware version |
| `RatedPower` | `36068` | `uint16` | Rated inverter power |
| `RunMode` | `36101` | `uint16` | Running mode |
| `BmsStatus` | `36102` | `uint16` | BMS status |
| `ErrCode_DSP` | `36103` | `uint16` | DSP error code |
| `ErrCode_BAT` | `36104` | `uint16` | Battery error code |
| `ErrCode_EMS` | `36105` | `uint16` | EMS error code |
| `INVSink_Temp` | `36106` | `int16`, scale `0.1` | Inverter heatsink temperature |
| `BatSink_Temp` | `36107` | `int16`, scale `0.1` | Battery heatsink temperature |
| `Ppv1` | `36112` | `uint16` | PV string 1 power |
| `Ppv2` | `36113` | `uint16` | PV string 2 power |
| `BatPower_BMS` | `36153` | `int32` | Signed battery power |
| `Power_Meter` | `36131` | `int32` | Signed grid meter power |
| `BatSOC` | `36155` | `uint16` | Battery state of charge |
| `SlaveError` | `37500` | `uint16` | Slave error status |
| `PowerLimitByBMSChg` | `37501` | `int16` | BMS charge power limit |
| `PowerLimitByBMSDisChg` | `37502` | `int16` | BMS discharge power limit |
| `battery_min_cap` | `60009` | `uint16` | Minimum battery capacity |

The configured RS485 parameters are 115200 baud, 8 data bits, no parity, 1 stop
bit, slave address `1`, and Modbus function `4`.

The RS485 poller groups contiguous due registers dynamically when port, slave,
function, and poll interval match. This means adding or removing adjacent
registers in `module_settings.json` automatically changes the Modbus read grouping.

`device_modules/validation.py` validates the loaded module settings at boot and
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
| `PV_p` | W | `Ppv1 + Ppv2` |
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

### Device Information, Running Data, and Diagnostics

WHES device information sensors are published as Home Assistant diagnostic
entities: `DeviceType`, `Manufacturer`, `SerialNumber_INV`, `DSP1_ver`,
`DSP2_ver`, `EMS_ver`, `BMS_ver`, `Hardware_Version`, and `RatedPower`.

WHES running data includes `RunMode`, `BmsStatus`, `ErrCode_DSP`,
`ErrCode_BAT`, `ErrCode_EMS`, `INVSink_Temp`, `BatSink_Temp`, `SlaveError`,
`PowerLimitByBMSChg`, and `PowerLimitByBMSDisChg`. Error/status and power-limit
metadata are diagnostic entities; temperature sensors are normal measurement
entities.

The firmware also publishes RS485 diagnostic entities for the last bus request:
`rs485_last_ok`, `rs485_last_operation`, `rs485_last_address`,
`rs485_last_error`, and `rs485_last_latency_ms`.

## EMS Boiler Monitor

`device_modules/ems.py` provides a read-only `EMS-Boiler` sensor subclass for
Bosch/Worcester EMS boilers. It expects an EMS-to-TTL interface board between
the boiler bus and the Pico UART; do not connect the Pico UART directly to the
boiler EMS bus.

The driver listens for broadcast monitor telegrams and publishes configured
values only after EMS CRC validation. It does not acknowledge polls, fetch
telegrams, or write settings, so it is intentionally a monitor-only first
implementation.

The example [module_settings.ems.example.json](module_settings.ems.example.json) uses UART0 on
GP0/GP1 at 9600 baud and includes common Greenstar 8000-style entities such as:

- heating and tap-water active flags
- flow, return, boiler, exhaust, and DHW temperatures
- system pressure
- burner state/current power
- flame current
- service code and EMS diagnostic counters

## MAX31865 PT1000 Temperature

`device_modules/max31865_pt1000.py` provides a `MAX31865-PT1000` sensor subclass
for the Adafruit MAX31865 RTD amplifier and a PT1000 probe. It reads the
MAX31865 over SPI and converts measured RTD resistance to temperature using the
Callendar-Van Dusen curve.

The example [module_settings.max31865_pt1000.example.json](module_settings.max31865_pt1000.example.json)
uses SPI0 with these default pins:

| Signal | Pico GPIO |
| --- | ---: |
| SCK | GP2 |
| MOSI | GP3 |
| MISO | GP4 |
| CS | GP5 |

Important config fields:

| Field | Purpose |
| --- | --- |
| `wires` | RTD wiring mode: `2`, `3`, or `4` |
| `rtd_nominal` | Probe nominal resistance; `1000` for PT1000 |
| `ref_resistor` | MAX31865 board reference resistor; Adafruit PT1000 boards usually use `4300` ohms |
| `filter_hz` | Mains filter selection, usually `50` in the UK |
| `precision` | Decimal places for published temperature/resistance |

The example publishes `temperature` as a normal Home Assistant temperature
sensor and optional diagnostic values for resistance, raw RTD count, and fault
status.

## Grove AC Voltage Sensor

`device_modules/grove_ac_voltage.py` provides a `Grove-AC-Voltage` sensor
subclass for the Grove AC Voltage Sensor based on the MCP6002 amplifier. The
board outputs a biased analogue AC waveform; the Pico samples it with ADC,
removes the DC midpoint, calculates RMS, and applies a configurable calibration
multiplier.

The example [module_settings.grove_ac_voltage.example.json](module_settings.grove_ac_voltage.example.json)
uses GP26/ADC0 and is aimed at typical 240V AC monitoring. It publishes:

- `voltage`, a calibrated RMS voltage sensor
- `ac_present`, an optional Home Assistant binary sensor
- ADC diagnostics: RMS counts, midpoint, min, max, and last error

Threshold behavior is configured under `ac_voltage`:

| Field | Purpose |
| --- | --- |
| `threshold` | Voltage at or above which the binary sensor turns on |
| `hysteresis` | Drop below `threshold - hysteresis` required before turning off |
| `threshold_key` | State key used by the binary sensor entity |

Remove the `ac_present` entity from the example config if you only want the
voltage sensor. The example includes a `_comment` field explaining calibration:
compare the published value with a known meter reading at 240V AC and adjust
`calibration` until the MQTT value matches reality.

## MQTT Topics

The Pico derives its MQTT device id from `machine.unique_id()`.

State is published to:

```text
homeassistant/sensor/<deviceid><uuid>/state
```

Home Assistant discovery config is published to:

```text
homeassistant/sensor/<deviceid><uuid>_<entity_id>/config
```

Modules may also publish other Home Assistant discovery components when needed.
For example, the Grove AC voltage threshold entity publishes discovery under:

```text
homeassistant/binary_sensor/<deviceid><uuid>_<entity_id>/config
```

For WHES, `<entity_id>` is based on the published key, such as `pv_p`,
`grid_import_e`, or `rs485_last_latency_ms`. The firmware publishes empty
retained payloads for the old numeric discovery topics so Home Assistant can
remove stale entities from earlier firmware versions.

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
`x10`, and payloads may use `16`, `"16"`, `"0x10"`, or `"x10"`. Use `value`
for a single scalar write, or `values` with an array when using function `16`
style writes:

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
- `module_settings.json`
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
  `grid_import_e`, `grid_export_e`, the WHES device information/running data
  sensors, and the RS485 diagnostic sensors.

## Host-Side Tests

The `tests/` directory contains a small `unittest` suite for logic that can run
without Pico hardware:

```sh
python3 -m unittest discover -s tests
```

The tests cover WHES presentation calculations, rounded daily energy values,
EMS telegram decoding, MAX31865 PT1000 conversion, Grove AC voltage RMS and
threshold behavior, local display rendering/actions, Home Assistant topic
helpers, and config validation.

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
