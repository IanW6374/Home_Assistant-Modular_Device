# Home Assistant Modular Device

Cross-platform MicroPython firmware for Raspberry Pi Pico W/Pico 2 W and
ESP32-S3 that exposes modular devices to Home Assistant over MQTT. Modules are
described in `module_settings.json`, discovered at boot, and handled by small
driver modules in `device_modules/`. ESP32-S3-DevKitC-1-N8R8 is the preferred
development target for HTTPS and full base-firmware OTA.

The checked-in `module_settings.json` is the active device configuration for a
target device. Additional configs in `examples/` cover standalone Pico devices
and ESP32-S3 starting points for EMS monitoring and PT1000 temperature sensing.

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
- Lightweight web dashboard with logs, module health, discovery trigger, and
  Grove AC voltage calibration.
- MQTT availability and diagnostic health entities for easier field debugging.

## Repository Layout

```text
main.py                         Boot entry point, executes HA-Device.py
app_update.py                   Transactional Python application updater
firmware_update.py              ESP32 dual-partition base firmware updater
hardware_platform.py            RP2/ESP32 capability and hardware abstraction
HA-Device.py                    WiFi, MQTT, discovery, and device orchestration
module_settings.json            Module and register configuration
device_settings.json            Local firmware settings
settings_loader.py              Required JSON settings loader and validator
local_display.py                Optional SH1107 OLED status display service
examples/                       Example module settings and credential templates
examples/module_settings.whes.example.json WHES inverter example configuration
examples/module_settings.ems.example.json EMS boiler example configuration
examples/module_settings.max31865_pt1000.example.json PT1000/MAX31865 example configuration
examples/module_settings.grove_ac_voltage.example.json Grove AC voltage example configuration
examples/module_settings.dual_pt1000_voltage_display.example.json Combined PT1000/voltage/display example
secrets.py                      WiFi and MQTT credentials, not suitable for commits
examples/secrets.example.py     Template for local credentials
device_modules/                 Device driver modules
device_modules/whes.py          WHES inverter presentation/calculation driver
device_modules/pico_2ch_rs485.py Generic RS485 Modbus driver
device_modules/ems.py           Read-only EMS boiler monitor
device_modules/max31865_pt1000.py MAX31865 PT1000 RTD driver
device_modules/grove_ac_voltage.py Grove AC voltage ADC driver
device_settings.schema.json     Host-side JSON schema for firmware settings
module_settings.schema.json     Host-side JSON schema for module settings
tools/deploy.py                 Host-side helper for copying MicroPython files
tools/build_update.py           Selective Python application bundle builder
tools/build_firmware_update.py  ESP32 .app-bin to .hamf firmware bundle builder
firmware/                       ESP32 OTA partition layout
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

### `device_settings.json`

`device_settings.json` is required. The firmware stops at startup if this file
is missing, is not valid JSON, or does not contain the required settings. It
selects the module settings file, certificate path, Home Assistant discovery
behavior, and NTP servers:

```json
{
  "device": {
    "name": "Test1",
    "module_settings_file": "module_settings.json",
    "ca_cert_path": "/certs/home-ca.der",
    "loglevel": "INFO",
    "watchdog_timeout_ms": 0,
    "ntp_servers": [
      "pool.ntp.org",
      "time.google.com"
    ]
  },
  "ha": {
    "discovery": true,
    "discovery_cleanup_legacy_identity": false,
    "discovery_cleanup_legacy": false,
    "system_diagnostics": true,
    "device_info": {
      "mf": "Home",
      "mdl": "PicoW",
      "sw": "1.3-beta",
      "hw": "1.0"
    }
  },
  "web_portal": {
    "enabled": false,
    "updates_enabled": false,
    "update_max_bytes": 2097152,
    "allow_protected_updates": false
  },
  "local_display": {
    "enabled": false
  }
}
```

If MQTT TLS is enabled, copy your CA certificate to the configured path on the
Pico. Set `watchdog_timeout_ms` to a positive value up to `8000` to enable the
Pico hardware watchdog after MQTT connects; the RP2040 hardware limit is about
`8388` ms. Leave it as `0` while developing over USB/REPL.

### Web Portal

The optional web portal exposes device status, loaded modules, module health,
recent values, runtime log level, recent firmware logs, Home Assistant discovery
triggering, and Grove AC voltage calibration. It is disabled by default. To
enable it, set
`"web_portal": {"enabled": true}` and add `web_portal_token` to `secrets.py`. The
portal binds to all network interfaces by default and logs the actual WiFi IP
address after startup.

Open the portal with:

```text
http://<pico-ip>:8080/?token=<web_portal_token>
```

When `"web_portal": {"port": null}`, the firmware uses `8080` for HTTP and `8443`
for HTTPS. Set `web_portal.port` to an integer only when you want a custom
port.

The portal accepts `ERROR`, `INFO`, and `DEBUG` log levels. Changes are runtime
only and are not written back to `device_settings.json`, so rebooting restores the
configured default. `DEBUG` also enables MQTT topic/payload logging and
`mqtt_as` client debug output. The log pane refreshes automatically using
`web_portal.log_refresh_s` and remains scrollable so earlier buffered log events can
be reviewed. Set `web_portal.value_refresh_s` to a positive interval when you
want status and module values to refresh in place automatically; leave it as
`0` to refresh only the log pane. The recent log
buffer is controlled by `web_portal.log_buffer_lines`, and very long individual
entries are trimmed to `web_portal.log_line_max_chars`. Use **Download logs** in
the portal controls to save the current in-memory buffer as
`ha-device-logs.txt`.

Portal cards use friendly display labels for shared health and diagnostic
fields, such as **Last operation OK**, **HA publish age**, and **EMS CRC
errors**. This is presentation-only; MQTT payload keys and Home Assistant entity
identifiers retain their original stable names.

For Grove AC voltage calibration, enter a known meter voltage in the portal.
The firmware updates the in-memory calibration multiplier and reports the new
value. Copy that value back to `module_settings.json` when you want it to
survive a reboot.

The portal defaults to HTTP because server-side TLS exhausted heap during Pico W
testing. If HTTPS is required on Pico W hardware, terminate TLS on a reverse
proxy such as Home Assistant, Caddy, or nginx and proxy to the Pico's HTTP
portal on the trusted LAN.

#### Pico 2 W HTTPS

Direct HTTPS hosting is supported only on Raspberry Pi Pico 2 W. The original
Pico W does not provide enough dependable MicroPython heap for concurrent MQTT
TLS, portal TLS, discovery, and module operation; use HTTP behind a TLS reverse
proxy on Pico W. Enable Pico 2 W HTTPS in
`device_settings.json`:

```json
{
  "web_portal": {
    "enabled": true,
    "https": true,
    "port": null,
    "cert_path": "/certs/web.crt.der",
    "key_path": "/certs/web.key.der"
  }
}
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

On Pico 2 W the HTTPS listener starts after initial Home Assistant discovery,
when temporary discovery payloads have been released. Portal HTML is rendered
and transmitted in bounded fragments, and automatic log/value refresh requests
are performed sequentially to avoid overlapping TLS handshakes. Startup logs
report free and allocated MicroPython heap before discovery and before the HTTPS
listener starts; the same values appear in the portal status cards.

### Remote Application Updates

Portal-based remote application updates, including protected secrets and
certificate maintenance, are supported on Pico 2 W and ESP32-S3. Pico 2 W
remains memory-constrained when MQTT TLS and portal HTTPS run together;
ESP32-S3 with PSRAM is the preferred target. Continue using local USB deployment
on the original Pico W.

The web portal can stream a staged application bundle to the Pico without
loading the complete upload into RAM. Enable the feature explicitly:

```json
{
  "web_portal": {
    "enabled": true,
    "updates_enabled": true,
    "update_max_bytes": 2097152,
    "allow_protected_updates": false
  }
}
```

Build a normal application bundle on the development machine. By default the
builder analyses `device_settings.json` and `module_settings.json` from the
repository root and includes only the drivers and library dependencies required
by the configured device types:

```sh
python3 tools/build_update.py update.hamd --version 1.4-beta
```

Analyse a different device/module combination explicitly:

```sh
python3 tools/build_update.py update.hamd --version 1.4-beta \
  --device-settings device_settings.json \
  --module-settings module_settings_EMS.json
```

When either `--device-settings` or `--module-settings` is supplied, both
selected settings files are automatically packaged—`--include-settings` is not
required. Their installed names are always normalized to `device_settings.json`
and `module_settings.json`, and the packaged device settings are rewritten to
reference `module_settings.json`. If neither option is supplied, settings are
only packaged when `--include-settings` is present. Missing or invalid selected
files stop the build.

The build report prints the selected settings files, configured class/subclass
pairs, and every packaged path. Relative imports between drivers are resolved
recursively—for example WHES adds the RS485 driver, while MAX31865 adds the
shared SPI helper. Switch drivers add their button primitives and HCSR04 adds
its sensor library. Unknown configured subclasses or missing dependencies stop
the build rather than creating an incomplete package.

Normal bundles contain the shared application core plus the selected drivers
and dependencies. They do not contain `main.py`, `app_update.py`, device
settings, module settings, credentials, or certificates. Include the analysed
settings explicitly when required:

```sh
python3 tools/build_update.py update.hamd --version 1.4-beta --include-settings
```

`.build_update_ignore` provides an additional filter for recursively collected
content. It excludes development-only files and directories such as
`examples/`, `tests/`, caches, editor backups, and macOS metadata. Add further
glob patterns there when local files should never enter an update bundle.

Upload the bundle in the portal, wait for SHA-256 verification to complete, and
then select **Activate and reboot**. The stable `main.py` recovery launcher
backs up every replaced file. The new application remains a trial until WiFi,
the web portal, and MQTT start successfully; otherwise the previous files are
restored on the next boot.

Application/runtime files in a bundle are always updated. Select **Upload and
stage** first; after the bundle has been verified, the portal shows only the
optional overwrite groups actually contained in it. Select the required
`device_settings.json`, `module_settings.json`, `secrets.py`, or `certs/`
groups immediately before **Activate and reboot**. Unchecked groups are skipped
during activation. Secrets and certificates additionally require
`web_portal.allow_protected_updates`.

Portal status shows **App version**, **Base version**, and **Staged version**.
The app version is the manifest version of the last confirmed application
bundle. The base version identifies the USB-installed `main.py`/`app_update.py`
recovery layer and is changed only when that protected layer is updated. A
protected-only credentials/certificate bundle does not change the app version.

Credentials and certificates require two explicit permissions. Set
`web_portal.allow_protected_updates` to `true`, then select the displayed
**Secrets** or **Certificates** overwrite option before activation. A
maintenance-only bundle can be built
with:

```sh
python3 tools/build_update.py protected.hamd --version credentials-2026-07 \
  --protected-only --include-protected \
  --certificate home-ca.der --certificate web.crt.der --certificate web.key.der
```

`--include-protected` includes the local `secrets.py` when it exists. Certificate
arguments are installed under `/certs/` using their filenames. Protected
updates should only be sent over HTTPS or a trusted, TLS-terminating reverse
proxy because an HTTP portal transmits credentials and private keys in clear
text. Application bundles cannot replace `main.py`, `app_update.py`, or
`firmware_update.py`; changes to that recovery layer still require a local USB
deployment.

### ESP32-S3 Base Firmware OTA

The ESP32-S3-DevKitC-1-N8R8 has 8 MB flash and 8 MB Octal PSRAM. Use the
MicroPython `ESP32_GENERIC_S3` **Octal-SPIRAM** build; the non-Octal build will
not expose the board's PSRAM correctly. The initial USB-installed image must
also enable ESP-IDF application rollback and use an OTA partition table with
`otadata`, `ota_0`, `ota_1`, and a separate VFS partition. This repository
provides `firmware/partitions-8MiB-ota.csv` as the required 8 MB layout and
`firmware/sdkconfig.ota` with the required rollback setting. These files are
inputs to a custom MicroPython/ESP-IDF build; copying them onto the board's VFS
does not change its partition table or bootloader.

A normal combined `.bin` is used only for the initial USB flash. Portal OTA
uses the MicroPython `.app-bin`, which contains only the application image for
the inactive OTA slot. Do not upload a combined `.bin` to the portal.

Enable the ESP32 firmware updater in `device_settings.json`:

```json
{
  "web_portal": {
    "firmware_updates_enabled": true,
    "firmware_update_max_bytes": 4194304
  }
}
```

Wrap a matching `.app-bin` on the development machine:

```sh
python3 tools/build_firmware_update.py \
  ESP32_GENERIC_S3-SPIRAM_OCT-v1.28.0.app-bin \
  micropython-1.28.0.hamf \
  --version micropython-1.28.0
```

Upload the `.hamf` file under **Base firmware update**. The device streams it
directly to the inactive partition, validates the package SHA-256, reads the
partition back, and verifies it again. **Activate firmware and reboot** changes
the boot partition only after verification. The new runtime remains a trial
until Wi-Fi, MQTT and the portal start; firmware built with rollback enabled
returns to the previous partition if the trial cannot confirm itself.
The tile shows both the running firmware label and any staged firmware label.

The Python filesystem, application settings, secrets and certificates live in
the separate VFS partition and are not overwritten by base-firmware OTA. Keep
using `.hamd` for routine Python application changes.

### ESP32-S3 Migration Configuration

Start with these checked-in examples:

- `examples/device_settings.esp32-s3-devkitc-n8r8.example.json`
- `examples/module_settings.esp32-s3-max31865.example.json`
- `examples/module_settings.esp32-s3-ems.example.json`

The platform layer disables the Pico-specific `Pin("LED")` default on ESP32,
removes the RP2 watchdog cap, publishes the detected platform/runtime, and
enables firmware OTA only when an inactive ESP32 OTA partition is actually
present. The Grove AC driver configures ESP32 ADC attenuation; its calibration
must still be repeated against a trusted meter because ESP32 and RP2 ADC
transfer characteristics differ.

Validate hardware in this order: Wi-Fi/MQTT and HTTPS portal, one MAX31865 SPI
module, EMS UART timing/CRC, Grove AC ADC/calibration, then the optional OLED.
The example pin assignments are a starting point and must be checked against
the carrier wiring before energising attached equipment.

### Local OLED Display

`local_display.py` adds an optional status display for Waveshare Pico-OLED-1.3
style SH1107 modules. It is disabled by default; enable it in
`device_settings.json` by setting:

```json
{
  "local_display": {
    "enabled": true
  }
}
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

When enabled, the display shows a compact status page with WiFi/MQTT state,
uptime, and recent alert count, then pages through current device payload
values. Module health details stay in the web portal; the OLED only shows a
module error when one is active. Short and long presses can page through
screens, request Home Assistant discovery, or toggle the runtime log level.

### Module Settings Files

`device_settings.json` points at the active module settings file through
`device.module_settings_file`. The default remains:

```json
{
  "device": {
    "module_settings_file": "module_settings.json"
  }
}
```

The selected module settings file is also required. The firmware stops at
startup if it is missing, is not valid JSON, or fails module validation.

The repo includes separate example configs for standalone Pico devices:

| File | Sensor subclass | Purpose |
| --- | --- | --- |
| `examples/module_settings.whes.example.json` | `WHES` | WHES inverter RS485/Modbus setup |
| `examples/module_settings.ems.example.json` | `EMS-Boiler` | Worcester/Bosch EMS boiler broadcast monitor |
| `examples/module_settings.max31865_pt1000.example.json` | `MAX31865-PT1000` | PT1000 RTD probe through a MAX31865 amplifier |
| `examples/module_settings.grove_ac_voltage.example.json` | `Grove-AC-Voltage` | Grove MCP6002 AC voltage measurement and optional AC-present binary sensor |
| `examples/module_settings.dual_pt1000_voltage_display.example.json` | `MAX31865-PT1000`, `Grove-AC-Voltage` | Two PT1000 probes plus Grove AC voltage, intended for use with the local OLED display |

Copy one of the example files or point `device.module_settings_file` at it on the target
Pico. Each example assumes a dedicated Pico for that hardware role.

Add `"retain_state": true` to a module if you want its state payload retained
by MQTT. This is useful for slow-changing values after a Home Assistant restart,
but it is intentionally opt-in.

For the combined PT1000/voltage/display example, set:

```json
{
  "device": {
    "module_settings_file": "examples/module_settings.dual_pt1000_voltage_display.example.json"
  },
  "local_display": {
    "enabled": true
  }
}
```

It allocates GPIOs this way. The two MAX31865 boards share the SPI0 clock/data
signals; only the chip-select line is different for each board.

| Hardware | Module pin/signal | Pico GPIO |
| --- | --- | ---: |
| MAX31865 flow probe | SCK | GP2 |
| MAX31865 flow probe | SDI / MOSI | GP3 |
| MAX31865 flow probe | SDO / MISO | GP4 |
| MAX31865 flow probe | CS / CSN | GP5 |
| MAX31865 return probe | SCK | GP2 |
| MAX31865 return probe | SDI / MOSI | GP3 |
| MAX31865 return probe | SDO / MISO | GP4 |
| MAX31865 return probe | CS / CSN | GP6 |
| Grove AC voltage sensor | OUT / ADC0 | GP26 |
| Waveshare Pico-OLED-1.3 display | SCK | GP10 |
| Waveshare Pico-OLED-1.3 display | MOSI | GP11 |
| Waveshare Pico-OLED-1.3 display | CS | GP9 |
| Waveshare Pico-OLED-1.3 display | DC | GP8 |
| Waveshare Pico-OLED-1.3 display | RST | GP12 |
| Display Key0 | Button input | GP15 |
| Display Key1 | Button input | GP17 |

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

Set `ems.debug_frames` to `true` temporarily to log every received UART buffer
as hexadecimal bytes. Each entry includes the buffer length and CRC result;
CRC failures also show the calculated and received CRC bytes. Debug-frame logs
are emitted at INFO level so no global logging change is needed. Disable the
setting after troubleshooting because an active EMS bus produces frequent log
entries.

Single-byte EMS device polls, acknowledgements, and grouped poll traffic are
reported as `short` or `bus activity` while frame debugging is enabled. They do
not increment `ems_crc_errors`; that counter applies only to malformed boiler
broadcast monitor telegrams supported by this driver.

The EMS module card in the web portal also provides an **Enable debug frames**
button. This toggles logging immediately for the running driver; it does not
rewrite `module_settings.json`, so the configured `debug_frames` value is used
again after a restart. The example and active configuration default to `false`.

The example [examples/module_settings.ems.example.json](examples/module_settings.ems.example.json) uses UART0 on
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

The example [examples/module_settings.max31865_pt1000.example.json](examples/module_settings.max31865_pt1000.example.json)
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

The example [examples/module_settings.grove_ac_voltage.example.json](examples/module_settings.grove_ac_voltage.example.json)
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
`calibration` until the MQTT value matches reality. The web portal can calculate
this runtime calibration multiplier from the current reading and a known meter
voltage.

## MQTT Topics

The Pico derives its raw hardware id from `machine.unique_id()`. The Home
Assistant/MQTT device id combines that raw id with the safe form of
`device.name` from `device_settings.json`, for example
`fb1bd968b107ea19_htw`. This keeps entities separate when the same Pico is
reconfigured as a different logical device name.

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
`grid_import_e`, or `rs485_last_latency_ms`. When migrating from firmware that
used only the raw Pico hardware id in discovery topics, set
`"ha": {"discovery_cleanup_legacy_identity": true}` so the firmware publishes
empty retained payloads for matching hardware-only config topics and Home
Assistant can remove stale entities. It can also publish empty retained payloads
for the old numeric discovery topics from earlier firmware versions when
`"ha": {"discovery_cleanup_legacy": true}`. Both cleanup options are disabled by
default to avoid unnecessary retained cleanup publishes after migration.

Availability is published to:

```text
homeassistant/status/<deviceid>/availability
```

Discovery payloads reference that topic and the firmware sets an MQTT last will
of `offline`; it publishes `online` after connecting.

When `"ha": {"system_diagnostics": true}`, the firmware also publishes diagnostic
entities for firmware version, active module settings file, loaded module count,
WiFi IP, uptime, and the last Home Assistant discovery payload count. Each
driver publishes module health diagnostics such as `module_last_ok`,
`module_last_error`, `module_last_read_ms`, `module_last_publish_age_s`, and
`module_consecutive_errors`.

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

## Running on MicroPython Hardware

Copy the project files to the MicroPython filesystem, including:

- `main.py`
- `app_update.py`
- `firmware_update.py`
- `hardware_platform.py`
- `HA-Device.py`
- `module_settings.json`
- `device_settings.json`
- `settings_loader.py`
- `secrets.py`
- `device_modules/`
- `lib/`
- any configured TLS certificate files

If the MicroPython filesystem is mounted on the host, the helper below copies the
runtime files and avoids caches/macOS metadata:

```sh
python3 tools/deploy.py /path/to/pico-mount
```

On boot, `main.py` runs `HA-Device.py`, connects WiFi/MQTT, loads device modules,
subscribes to relevant topics, publishes Home Assistant discovery payloads, and
starts each sensor driver.

## V1 Deployment Checklist

- Set `"device": {"watchdog_timeout_ms": 0}` while flashing or debugging over USB/REPL.
- Set `"device": {"watchdog_timeout_ms": 8000}` for deployment.
- Let the device connect to MQTT and publish Home Assistant discovery once.
- Confirm Home Assistant shows these WHES entities:
  `serial_number`, `PV_p`, `battery_p`, `grid_p`, `home_p`, `battery_soc`,
  `pv_e`, `home_e`, `battery_charge_e`, `battery_discharge_e`,
  `grid_import_e`, `grid_export_e`, the WHES device information/running data
  sensors, and the RS485 diagnostic sensors.

## Host-Side Tests

The `tests/` directory contains a `unittest` suite for logic that can run
without microcontroller hardware:

```sh
python3 -m unittest discover -s tests
```

The tests cover WHES presentation calculations, rounded daily energy values,
EMS telegram decoding, MAX31865 PT1000 conversion, Grove AC voltage RMS and
threshold behavior/calibration, local display rendering/actions, Home Assistant
topic/discovery helpers, web portal rendering, shared SPI handling, and config
validation.

`device_settings.schema.json` and `module_settings.schema.json` can be
associated with `device_settings.json`, `module_settings.json`, and
`examples/module_settings*.json` in your editor for lightweight host-side
validation.

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

- The code targets MicroPython on Raspberry Pi Pico W/Pico 2 W and ESP32-S3.
  ESP32-S3-DevKitC-1-N8R8 is preferred for direct HTTPS and base firmware OTA.
- ESP32 base firmware OTA requires an OTA partition table and a rollback-enabled
  initial firmware image; board type alone is not sufficient.
- MQTT discovery uses the `homeassistant/` topic prefix.
- Generated bytecode/cache files are not needed on the Pico.
- Keep credentials and certificates out of public repositories.
- `.gitignore` excludes local secrets, certificates, bytecode, and macOS cache
  files.
