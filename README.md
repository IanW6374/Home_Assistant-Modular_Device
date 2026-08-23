# HAMD — Home Assistant Modular Device

ESP32-S3 MicroPython firmware that exposes modular devices to Home Assistant
over MQTT. Modules are
described in `module_settings.json`, discovered at boot, and handled by small
driver modules in `device_modules/`. ESP32-S3-DevKitC-1-N8R8 is the supported
target for HTTPS and full base-firmware OTA.

The checked-in `module_settings.json` is the active device configuration for a
target device. Additional configs in `examples/` provide ESP32-S3 starting
points for EMS monitoring, RS485 devices, voltage sensing, and PT1000 sensing.

## Features

- Bounded, coalescing MQTT state publishing and Home Assistant MQTT discovery.
- Versioned HTTPS module API with simultaneous MQTT operation, read/write
  commands, mandatory mTLS, client-certificate enrolment, scopes, and revocation.
- Modular device drivers loaded from `device_modules/`.
- GPIO light and switch modules.
- Generic ESP32-S3 RS485 Modbus sensor module, with legacy configuration compatibility.
- WHES-specific RS485 module with calculated MQTT presentation entities.
- Read-only Bosch/Worcester EMS boiler monitor over an EMS-to-TTL interface.
- MAX31865/PT1000 RTD temperature sensor over SPI.
- Grove MCP6002 AC voltage sensor over ADC, with optional threshold binary
  sensor.
- Optional local display service with an SH1107 SPI driver.
- Responsive authenticated portal and first-boot wizard with DHCP/static IPv4,
  certificate enrollment, structured module configuration, and signed A/B
  application/core updates.
- Live logs, module health, discovery trigger, and Grove AC voltage calibration.
- MQTT availability and diagnostic health entities for easier field debugging.
- Persistent reset, watchdog, Wi-Fi/RSSI, heap, MQTT-drop, startup-exception,
  certificate-expiry, and update-result health history.
- Versioned non-secret configuration export/import with validation and diff preview.
- Reboot-safe paired core/application release orchestration.
- Resumable, digest-verified `.hamd`, `.hamf`, and policy-rich `.hamu` uploads.
- Multi-user viewer/operator/administrator portal access with independent
  sessions and CSRF tokens.
- Structured events, redacted support bundles, signed fleet policy and a Home
  Assistant ingress add-on for inventory, health and staged rollout cohorts.

## Repository Layout

```text
main.py                         Boot entry point, executes HA-Device.py
app_update.py                   Transactional Python application updater
firmware_update.py              ESP32 dual-partition base firmware updater
hardware_platform.py            ESP32-S3 capability and hardware abstraction
HA-Device.py                    WiFi, MQTT, discovery, and device orchestration
application/                    Explicit application context, lifecycle and task ownership
module_settings.json            Module and register configuration
device_config.py                Immutable hardware/security policy frozen into core
app_settings.json               Signed application policy carried in every app bundle
app_settings.schema.json        Host-side schema for signed application policy
settings_loader.py              Combines frozen, signed-app, and encrypted user settings
display.py                      Generic local display service and driver registry
examples/                       Example ESP32-S3 module configurations
examples/module_settings.whes.example.json WHES inverter example configuration
examples/module_settings.ems.example.json EMS boiler example configuration
examples/module_settings.max31865_pt1000.example.json PT1000/MAX31865 example configuration
examples/module_settings.grove_ac_voltage.example.json Grove AC voltage example configuration
examples/module_settings.dual_pt1000_voltage_display.example.json Combined PT1000/voltage/display example
credential_store.py             Flash- and NVS-encrypted credential storage
credential_security.py          Native-backed password hashing and validation
setup_wizard.py                 Frozen first-boot AP setup and signed app installer
factory_config.py               Frozen non-secret app-profile/release catalogue
certificate_manager.py          Self-signed, manual, and ACME certificate lifecycle
api_security.py                 API client certificate enrolment and scopes
device_api.py                   Versioned, mandatory-mTLS module API
message_broker.py               Shared command broker and bounded MQTT output queue
runtime_health.py               Flash-conscious persistent health history
configuration_manager.py        Public and AES-GCM encrypted full backup/restore
remote_logging.py               Bounded RFC 5424 UDP/TLS syslog forwarding
update_orchestrator.py          Persistent paired core/application update state
portal_ui.py                    Shared portal/wizard visual components
web_portal.py                   Authenticated portal routes and rendering
web_portal_ui.py                Portal navigation, styling, and browser behavior
component_versions.py           Signed universal-runtime component version
services/                       Narrow network/module/MQTT/portal/update/event adapters
fleet_management.py             Signed device-side fleet policy and command state
resumable_upload.py             Power-safe update upload sessions
support_bundle.py               Bounded secret-redacted support snapshots
portal_auth.py                  Portal users, roles and route policy
portal_contracts.py             Named portal-to-application dependency contract
portal_routes.py                Versioned route authorization registry
portal_view_models.py           Transport-neutral portal presentation models
portal_sessions.py              Independent expiring portal sessions and CSRF
home_assistant_addons/hamd_fleet Home Assistant fleet-manager add-on
device_modules/                 Device driver modules
device_modules/contracts.py     Versioned driver metadata/capability contract
device_modules/resources.py     Deterministic GPIO/UART/SPI/ADC allocation preflight
device_modules/whes.py          WHES inverter presentation/calculation driver
device_modules/rs485_modbus.py   Generic ESP32-S3 RS485 Modbus driver
device_modules/ems.py           Read-only EMS boiler monitor
device_modules/max31865_pt1000.py MAX31865 PT1000 RTD driver
device_modules/grove_ac_voltage.py Grove AC voltage ADC driver
module_settings.schema.json     Host-side JSON schema for module settings
tools/deploy.py                 Host-side helper for copying MicroPython files
tools/build_update.py           Selective Python application bundle builder
tools/build_firmware_update.py  ESP32 application image to .hamf bundle builder
tools/build_universal_update.py Signed .hamf + .hamd to combined .hamu builder
tools/build_micropython_firmware.py Reproducible MicroPython build/package helper
tools/stage_application_usb.py  State-preserving signed application USB installer
tools/stage_firmware_usb.py     State-preserving signed core-firmware USB installer
tools/reseed_device_usb.py      Secured-device first-run reseed helper
tools/provision_update_signing.py Update public-key provisioning helper
docs/UPGRADE_GUIDE.md           Complete application/core/new-device procedures
firmware/                       ESP32 OTA partition layout
tests/                          Host-side unit tests
docs/ARCHITECTURE.md            Clean-seed v2 dependency and persistence model
lib/                            MicroPython support libraries
```

## Configuration

### First-boot setup wizard

There is no runtime `secrets.py`. A production factory image contains a unique
per-device setup AP key in encrypted NVS. On first boot the frozen supervisor
starts `HAMD-Setup-xxxxxx`; connect using the password in the build's mode-0600
setup-password output, then browse to `http://192.168.4.1`.

The wizard collects only the bootstrap settings needed to secure and join the
device: device name, Wi-Fi, portal login and transport, and independently
confirmed recovery AP/console passwords. After the browser supplies current
UTC, the editable `.local` hostname is initially derived from the device name.
The device then creates a unique self-signed portal certificate and key on its
flash-encrypted filesystem.
HTTPS is therefore available without a CA; ACME enrollment or a manually
supplied portal certificate and key can atomically replace that fallback.
MQTT broker credentials are configured after first boot under **System >
MQTT**. The release channel and automatic-update policy live under
**Maintenance > Upgrades**.
Portal and recovery login passwords are strength-checked and converted immediately to
salted PBKDF2 verifiers. Recoverable Wi-Fi, MQTT, and AP secrets live only in
ESP-IDF encrypted NVS; uploaded certificate material lives on the
flash-encrypted VFS.

The authenticated settings pages can change the device name, Wi-Fi network,
MQTT server/port/credentials, portal username, transport, and listener port
without reflashing. Stored passwords are never sent back to the browser: a
masked field denotes a stored value, an empty submission retains it, and typing
a new value replaces it. DHCP is the default; a static IPv4 address, subnet
mask, default gateway, and DNS server can be supplied in both the wizard and
the permanent portal. Network changes start a three-minute trial. The first
authenticated login confirms the new settings; otherwise the next boot restores
the complete previous configuration automatically. The core recovery AP remains
available for faults outside that transaction.
Both the wizard and permanent portal show a background-refreshed list of visible
Wi-Fi networks, ordered by signal strength. A manual SSID option remains
available for hidden networks. HTTP requests return the cached list immediately
so a radio scan cannot hold a portal response open.

The shipping/reseed process preloads a correctly signed application bundle on
the flash-encrypted filesystem. The wizard verifies and activates it after
certificate setup, then waits for the permanent portal and opens its login
page. `factory_config.py` defines an optional HTTPS release endpoint and signed
`.hamd` upload remains a recovery fallback when the preloaded application
cannot be verified. There is no shared fleet-wide default password.

MQTT, release-server, and API-client authentication use independent CA trust
anchors. An RC1 shared trust anchor remains a migration fallback until a
service-specific MQTT or release CA is installed. Each CA can then be rotated
without changing the portal identity or another outbound service. With ACME
enabled, the device answers HTTP-01 on port 80 and
renews at about two-thirds of the certificate lifetime; successful renewal
restarts the portal so it loads the new keypair. **Maintenance > Certificates**
retains manual replacement when the CA or ACME service is unavailable.

The TLS CA, update-signing key, Secure Boot v2 key, and per-device flash
encryption keys are independent trust domains. The CA never derives or holds
the update-signing or secure-boot private keys; devices contain only the update
public key and the secure-boot eFuse digest.

### Configuration ownership

Configuration has three explicit owners; the former monolithic
`device_settings.json` is not supported:

- `device_config.py` is immutable device and security policy frozen into the
  signed core firmware. It owns hardware identity, pins, watchdog/recovery
  policy, TLS paths, listener ports, and update limits.
- `app_settings.json` is signed application policy included in every `.hamd`
  application bundle. It owns Home Assistant behavior, portal features and
  refresh timing, release endpoints/timing, and local-display policy.
- User settings live in encrypted NVS. **System** owns Network, Portal,
  Time / Date, MQTT, Home Assistant, Device API, and Logging settings;
  **Maintenance > Upgrades** owns the release channel and automatic-update
  policy. Maintenance viewers link back to the applicable System configuration.

NTP always sets the RTC in UTC. **System > Time / Date** stores a named time
zone and applies its daylight-saving rules to portal timestamps, device logs,
scheduled release checks, and local-midnight energy resets without altering TLS
certificate validation. UTC remains the default.

`module_settings.json` remains the device's user-owned module configuration. A
missing file means zero configured modules. Use **Module > Configuration** to
load a JSON file or work in the structured advanced editor. **Verify and apply
configuration** performs JSON and module-driver validation, retains a validated
previous generation, writes the replacement, and restarts the device.

### Web Portal

The web portal uses the same responsive visual system as first-boot setup and
separates work by task:

- **Status > Overview** shows connectivity, versions, and MQTT-published module
  values.
- **System** separates Network, Portal, Time / Date, MQTT, Home Assistant,
  Logging, and the mTLS Device API settings.
- **Module** contains structured configuration and module diagnostics/support
  downloads.
- **User > Account** combines administrator identity and authenticated password
  replacement; legacy direct password-change URLs are disabled.
- **Maintenance** contains upgrades, configuration backup/restore, persistent
  health history, logging, the guarded factory-default
  action, and decoded certificate information split into **CA Trust** and
  **Device Certificates** sections for independent service identities.

**Maintenance > Factory default** requires the current administrator password,
an exact reset confirmation, and a new strong setup-AP password entered twice.
The reset request is completed idempotently by the immutable recovery layer on
reboot. It removes user/network/MQTT settings, module configuration,
certificates/ACME state, pending updates, and update history, then opens the
first-boot wizard. The signed core, confirmed application slots, firmware and
application release counters, and OTA verification public key are retained.

Portal transport defaults to HTTPS whenever an installed self-signed, ACME, or
manually uploaded certificate/key pair is available.
The encrypted portal username defaults to `admin` until it is changed under
**User > Account**. The portal binds to all network interfaces by default and
logs the actual Wi-Fi IP address after startup.

Open the portal with:

```text
https://<device-ip>:8443/
```

Sign in with the administrator password chosen during first boot. Passwords
must use at least 16 characters with sufficient variety, or a varied passphrase
of at least 20 characters. Common, repeated, and predictable values are
rejected. Only a salted PBKDF2 verifier is stored on the device. HTTPS is the
default; an administrator may explicitly select HTTP for a network where
transport encryption is not required.

The portal always shows and exports the effective port: HTTPS uses `8443` and
explicit HTTP uses `8080` by default. Port `80` remains reserved for ACME
HTTP-01 and recovery. The inactivity timeout is user-configurable from 5
minutes to 24 hours.

HAMD v2 supports up to eight portal identities. A viewer can inspect status,
diagnostics, health and logs; an operator can also execute module and approved
upgrade actions; an administrator owns configuration, trust, users and reset.
Every login has an independent expiring session and CSRF token. Disabling a
user or replacing its password invalidates all of that user's sessions.

**System > Logging** accepts `ERROR`, `INFO`, and `DEBUG` log levels. Changes
are saved to encrypted NVS and survive restart. `DEBUG` also enables MQTT
topic/payload logging and `mqtt_as` client debug output. The log pane refreshes
using `web_portal.log_refresh_s`; Overview refreshes its compact status using
`web_portal.value_refresh_s` (with a five-second fallback). The recent log
buffer is user-configurable from 0 to 500 entries, while the signed application
policy supplies its initial default. Long entries are trimmed to
`web_portal.log_line_max_chars`. Logs can also be forwarded as RFC 5424 to UDP
syslog or over authenticated TLS using the dedicated Syslog CA. **Pause** and **Resume** control
automatic log refresh without stopping device logging, while **Download logs**
saves the current buffer. **Module > Diagnostics > Download diagnostics**
exports status, module detail, and the last 100 log entries as JSON.
Successful and rejected portal logins, authenticated portal actions, and API
requests are written as audit entries; high-frequency browser refresh requests
are excluded to keep the bounded log useful.

**Maintenance > Health history** retains grouped system, network, MQTT, and API
counters plus timestamped significant events across restarts. Writes are
batched to reduce flash wear; startup/update failures are checkpointed
immediately, and an authenticated control can reset the complete history.
**Configuration backup** offers both a public operational backup with diff
preview and a complete password-encrypted backup. Complete backups use
PBKDF2-SHA256 and AES-256-GCM and include encrypted-NVS credentials, secrets,
module settings, certificates/private keys, ACME state, API trust anchors, and
enrolled API clients. Restore authenticates and validates the file before
activation and restart. Complete export and restore are refused when the portal
is running over explicit HTTP so the backup password never crosses the network
in plaintext.

**Maintenance > Upgrades** shows the persisted result of the last release check
without contacting the server merely because the page was opened. A manual
check action remains available. Disabled, daily, or weekly automatic checks run
at the configured local time; the weekday control applies only to weekly
schedules and irrelevant controls are disabled. Automatic and manual upgrade cards are
stacked in workflow order; after upload/download verification, the relevant
action changes to activation rather than presenting a second competing flow.
When a signed channel contains matching core and application releases, the
device records a two-step transaction, installs core firmware first, confirms
the trial after the portal health boundary, and resumes the application step
after reboot. The portal displays **step 1 of 2** or **step 2 of 2**.

Portal cards use friendly display labels for shared health and diagnostic
fields, such as **Last operation OK**, **HA publish age**, and **EMS CRC
errors**. This is presentation-only; MQTT payload keys and Home Assistant entity
identifiers retain their original stable names.

For Grove AC voltage calibration, enter a known meter voltage in the portal.
The firmware validates and transactionally writes the new multiplier back to
`module_settings.json`, so it survives power loss and restart, then returns to
**Module > Diagnostics**.

#### ESP32-S3 HTTPS

The portal is optimized for ESP32-S3 with PSRAM and supports direct HTTPS.
It uses `/certs/web.crt.der` and `/certs/web.key.der`, with those immutable
paths defined by frozen `device_config.py`. First boot creates a self-signed
pair, which can later be replaced through ACME or **Maintenance > Certificates**.
The `auto` user transport setting therefore selects HTTPS by default.

### Device API

Enable the API under **System > Device API**, using a port different from the
portal (default `8444`). Install one or more independent API client CAs and
enrol DER client certificates under **Maintenance > Certificates**. Multiple
CAs or clients can be staged as one batch. CA changes restart the TLS listener
once; client enrolment is active immediately without restart. The calling system
retains the corresponding private key; the device stores only the CAs and the
enrolled certificate fingerprint/scopes. The listener waits for a valid clock
and always requires a CA-validated, enrolled client certificate.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v2/device/inventory` | Fleet-safe identity, versions, capabilities and driver inventory |
| `GET /api/v2/modules` | Module identities and capabilities |
| `GET /api/v2/modules/{uuid}/state` | Latest cached state |
| `GET /api/v2/modules/{uuid}/diagnostics` | Driver and transport health |
| `POST /api/v2/modules/{uuid}/commands` | Submit the same JSON command used by MQTT `/set` |
| `GET /api/v2/operations/{id}` | Retrieve queued/deferred command status |
| `GET /api/v2/health` | Current health and bounded history snapshot |
| `GET /api/v2/events?cursor=N&limit=M` | Cursor-based structured audit/health events |
| `GET /api/v2/support` | Secret-redacted bounded diagnostic bundle |
| `GET /api/v2/fleet` | Applied policy, rollout and command state |
| `POST /api/v2/fleet/policy` | Apply a device/cohort-targeted signed fleet policy |
| `POST /api/v2/fleet/commands/{id}/result` | Complete a bounded fleet command |

API and MQTT commands enter the same bounded broker and driver path. Deferred
Modbus responses retain their request ID, and writes from either transport
update the shared state used by both. Cached `GET` requests do not initiate
physical bus traffic; use an explicit read command when a fresh transaction is
required. API requests are logged, counted in persistent health history, and
HTTP/1.1 connections can be reused to avoid a new TLS handshake for every
request. Unknown module UUIDs return a JSON `404` response.

For each API caller, issue a client certificate from the dedicated API client
CA, convert only the public certificate to DER, and enrol that `.der` file in
the portal. Keep the PEM private key on the caller. A request then supplies the
client identity and separately verifies the device's portal certificate, for
example:

```sh
curl --cert automation-client.crt --key automation-client.key \
  --cacert portal-ca.crt \
  https://device-name.local:8444/api/v2/modules
```

Revocation is immediate for new connections and is available under **System >
Device API**. The API has no password, bearer-token, or unauthenticated mode.

### Home Assistant fleet add-on

`home_assistant_addons/hamd_fleet` is an ingress-only Home Assistant add-on for
one device or a future fleet. It polls `/api/v2` using a dedicated mTLS client,
retains bounded structured events, displays inventory and health, and signs
maintenance/update policies using an independent P-256 management key. Ordered
canary/main cohorts advance explicitly and stop at their configured failure
threshold. The add-on never receives the release-signing or Secure Boot key.
See [`docs/FLEET_PROTOCOL.md`](docs/FLEET_PROTOCOL.md) and the add-on README.
Signing-key rotation and compromise response are documented in
[`docs/SECURITY_OPERATIONS.md`](docs/SECURITY_OPERATIONS.md).

For development-only manual certificate creation:

```sh
openssl genrsa -traditional -out web.key 1024
openssl req -new -x509 -key web.key -out web.crt -days 365 \
  -subj "/CN=esp32-web-portal"
openssl rsa -in web.key -outform DER -out web.key.der
openssl x509 -in web.crt -outform DER -out web.crt.der
```

Copy `web.key.der` and `web.crt.der` to `/certs/`. Portal responses are encoded
and buffered once, browser log/value refreshes run in parallel, and the listener
allows multiple queued connections. This assumes the PSRAM-enabled MicroPython
build described in the ESP32-S3 firmware section.

### Remote Application Updates

Portal-based remote application updates, including explicitly authorized
protected certificate maintenance, are supported on ESP32-S3 with PSRAM.
Encrypted-NVS credentials are never carried in an update bundle or public
configuration backup; they appear only inside the explicitly requested,
password-encrypted complete backup. Update size ceilings and protected-update permission are
immutable limits in `device_config.py`; they are not signed application
settings.

The web portal can stream a staged application bundle to the ESP32-S3 without
loading the complete upload into RAM. Enable the feature in signed application
policy:

```json
{
  "web_portal": {
    "enabled": true,
    "updates_enabled": true,
    "firmware_updates_enabled": true
  }
}
```

Build an application bundle on the development machine. Every application
bundle contains the universal runtime and all production drivers; each device
imports only the drivers referenced by its local module settings:

```sh
python3 tools/build_update.py update.hamd --version 1.4-beta \
  --release-sequence 1400 \
  --signing-key ~/.ham-device/update.private-key
```

Optionally offer a replacement module configuration:

```sh
python3 tools/build_update.py update.hamd --version 1.4-beta \
  --release-sequence 1400 \
  --module-settings examples/module_settings.ems.json \
  --signing-key ~/.ham-device/update.private-key
```

Module settings are an optional activation group and default to unchecked.
`app_settings.json` is mandatory signed application content and is installed
inside the new application slot.

The build report prints the selected settings files, configured class/subclass
pairs, and every packaged path. Relative imports between drivers are resolved
recursively—for example WHES adds the RS485 driver, while MAX31865 adds the
shared SPI helper. Switch drivers add their button primitives and HCSR04 adds
its sensor library. Unknown configured subclasses or missing dependencies stop
the build rather than creating an incomplete package.

Application bundles contain the application core and every production driver.
They do not contain the permanent `main.py` launcher or the
firmware-frozen recovery, update-security, universal-update, storage-support,
hardware-platform, and Wi-Fi recovery modules. User settings, module settings, credentials and
certificates are excluded by default. Include module settings explicitly when
required:

```sh
python3 tools/build_update.py update.hamd --version 1.4-beta \
  --release-sequence 1400 --include-module-settings \
  --signing-key ~/.ham-device/update.private-key
```

The universal runtime is now the only application format, so one signed file
can update the fleet without a device profile:

```sh
python3 tools/build_update.py application-1.5.0.hamd \
  --version 1.5.0 \
  --release-sequence 1500 \
  --signing-key ~/.ham-device/update.private-key
```

The signed manifest and release descriptor carry `RUNTIME_VERSION` plus each
driver's `MODULE_VERSION`. A device skips a newer release sequence when the
runtime is unchanged and none of its configured drivers has a newer version.
Increment the runtime version for shared/core changes and the affected driver
version for isolated module changes.

Release sequences are signed, positive, and monotonically increasing per bundle
type. A device refuses an application or firmware sequence that is not newer
than its confirmed sequence, even if the version label is different.

`.build_update_ignore` provides an additional filter for recursively collected
content. It excludes development-only files and directories such as
`examples/`, `tests/`, caches, editor backups, and macOS metadata. Add further
glob patterns there when local files should never enter an update bundle.

Upload the bundle in the portal, wait for signature and SHA-256 verification to complete, and
then select **Activate and reboot**. The recovery supervisor writes application
files into the inactive `.app-slots/a` or `.app-slots/b` directory and marks it
as a trial. The active slot pointer changes only after WiFi and the authenticated
web portal start successfully. MQTT is an external, portal-repairable service
and is not part of application health. Otherwise the failed slot is removed and the previous
slot starts on the next boot.

`module_settings.json` and certificates remain shared. Selected replacements
are backed up transactionally. User settings remain in encrypted NVS and
cannot be replaced by application updates.

Application/runtime files in a bundle are always updated. Select **Upload and
stage** first; after the bundle has been verified, the portal shows only the
optional overwrite groups actually contained in it. Select the required
`module_settings.json` or `certs/`
groups immediately before **Activate and reboot**. Unchecked groups are skipped
during activation. Certificates additionally require
`device_config.WEB_PORTAL_ALLOW_PROTECTED_UPDATES`.

Portal status shows **Application**, **Core firmware**, **MicroPython version**,
and any staged version. Application and core use the same HAMD product-release
label, while MicroPython is reported independently from `sys.implementation`.
A certificate-only bundle does not change the application version.

Certificates require two explicit permissions. Set
`device_config.WEB_PORTAL_ALLOW_PROTECTED_UPDATES` to `True` in the signed core,
then select the displayed
**Certificates** overwrite option before activation. A maintenance-only bundle can be built
with:

```sh
python3 tools/build_update.py protected.hamd --version credentials-2026-07 \
  --release-sequence 202607 \
  --protected-only --include-protected \
  --certificate trust/home-rca-root.der=home-rca-root.der \
  --certificate web.crt.der --certificate web.key.der \
  --signing-key ~/.ham-device/update.private-key
```

Certificate arguments accept either `PATH` (installed as `/certs/<basename>`)
or `TARGET=PATH`, where `TARGET` is relative to `/certs/`. The portal
requires HTTPS. Application bundles cannot replace the permanent launcher,
verification key, encrypted credential store,
or frozen recovery modules. Recovery changes are delivered in a rollback-protected
`.hamf` firmware update instead.

Generate the ECDSA P-256 update private key once and provision only its public
verification key on each device. The private key never leaves the signing host;
all unsigned or legacy-HMAC bundles are rejected:

```sh
python3 tools/provision_update_signing.py \
  --private-key ~/.ham-device/update.private-key --generate
python3 tools/provision_update_signing.py \
  --private-key ~/.ham-device/update.private-key --mount /path/to/device-mount
```

Production builds additionally enable ESP32-S3 Secure Boot v2, AES-256 release-
mode flash encryption, NVS encryption, and JTAG lockdown. The build helper
requires an explicit `--production-security` acknowledgement because first boot
permanently burns security eFuses.

### ESP32-S3 Base Firmware OTA

The ESP32-S3-DevKitC-1-N8R8 has 8 MB flash and 8 MB Octal PSRAM. Use the
project-owned `HAM_ESP32_S3` board with its `SPIRAM_OCT` variant; it derives
the appropriate upstream ESP32-S3 and Octal-SPIRAM settings. The initial
USB-installed image must
also enable ESP-IDF application rollback and use an OTA partition table with
`otadata`, `ota_0`, `ota_1`, and a separate VFS partition. This repository
provides `firmware/partitions-8MiB-ota.csv` as the required 8 MB layout and
`firmware/sdkconfig.ota` with the required rollback setting. These files are
inputs to a custom MicroPython/ESP-IDF build; copying them onto the board's VFS
does not change its partition table or bootloader.

The project-owned `firmware/boards/HAM_ESP32_S3` board definition and
`tools/build_micropython_firmware.py` apply the OTA settings, partition table,
frozen manifest, firmware size limit, and build version lock without modifying
the upstream `ESP32_GENERIC_S3` board. The manifest adds the complete recovery
and update-security layer to each ESP32 application image while retaining the
standard ESP32 frozen modules. The first installation requires a full USB
flash; an application-only image or `.hamf` contains no partition table and
cannot perform this initial migration.

The production board is deliberately Wi-Fi-only: Bluetooth/NimBLE, PPP and SPI
Ethernet are excluded from the immutable core, and ESP-IDF is compiled for
size. The reproducible build rejects those components if they are accidentally
re-enabled or linked. Core images warn at 80% of an OTA slot and fail the build
at 85%, preserving at least 15% for security and recovery maintenance. Wired or
Bluetooth support must be introduced as an explicit hardware-profile decision,
not inherited from the generic MicroPython board.

The complete, version-pinned procedures for application upgrades, core
upgrades, and first installation are in
[docs/UPGRADE_GUIDE.md](docs/UPGRADE_GUIDE.md). They also explain which
commands run under host Python 3 and which files are validated as MicroPython.

Build and package with:

```sh
python3 tools/build_micropython_firmware.py \
  --micropython-root /path/to/micropython \
  --version 1.5.0 \
  --release-sequence 1500 \
  --output releases/release-site-1.5.0/bundles/ham-core-1.5.0.hamf \
  --factory-output releases/factory-artifacts/ham-core-1.5.0.factory.bin \
  --signing-key ~/.ham-device/update.private-key \
  --production-security \
  --secure-boot-signing-key ~/.ham-device/secure_boot_signing_key.pem \
  --factory-setup-password-output releases/factory-artifacts/device-001.setup-password.txt
```

Release output is deliberately separated into deployable and factory-only
artifacts:

Application and core descriptors use the same product release version. Keep
component names in artifact filenames; the independently reported MicroPython
version does not form part of the HAMD core version.

```text
releases/
├── release-site-<version>/
│   ├── <channel>/latest.json
│   └── bundles/
│       ├── application-<version>.hamd
│       └── ham-core-<version>.hamf
└── factory-artifacts/
    ├── ham-core-<version>.factory.bin
    └── <device>.setup-password.txt
```

Copy only a `release-site-<version>` directory's contents to the update
server. The device-specific factory image and its setup password remain
offline together under `factory-artifacts`.

To check a running board from the MicroPython REPL:

```python
import esp32
running = esp32.Partition(esp32.Partition.RUNNING)
print('running:', running.info())
target = running.get_next_update()
print('next update:', target.info() if target else None)
```

An OTA-ready board should report `ota_0` or `ota_1` as the running partition
and the other slot as the next update. A `factory` running partition with no
next update means the board still needs the one-time custom USB installation.

A packaged `.factory.bin` is used only for the initial USB flash; it includes
the unique encrypted factory NVS and must not be replaced with MicroPython's
unmodified combined `firmware.bin`. Portal
OTA uses the application-only `micropython.bin` generated by the pinned source
build (some distributed builds call it `.app-bin`). Do not upload the combined
`firmware.bin` to the portal.

The signed `app_settings.json` controls whether the firmware updater is
visible. Its maximum accepted image size and protected-update permission are
immutable limits in frozen `device_config.py`.

Wrap a matching application-only image on the development machine:

```sh
python3 tools/build_firmware_update.py \
  --input /path/to/build-HAM_ESP32_S3-SPIRAM_OCT/micropython.bin \
  --output ham-core-1.5.0.hamf \
  --version 1.5.0 \
  --release-sequence 1500 \
  --platform esp32-s3 \
  --signing-key ~/.ham-device/update.private-key
```

`--input` is the MicroPython application-only `micropython.bin` (or a
distributed `.app-bin`) produced by the firmware build.
`--output` is the `.hamf` bundle to upload through the web portal.

Format 6 intentionally has no legacy bridge. Reflash a matching format-6
factory/core image before installing format-6 application releases.

Upload the `.hamf` file under **Maintenance > Upgrades**. The same manual
chooser accepts application `.hamd` bundles and combined `.hamu` bundles, and
routes each bundle type to the appropriate
verified update handler. The device streams the firmware bundle
directly to the inactive partition, validates the package SHA-256, reads the
partition back, and verifies it again. **Activate firmware and reboot** changes
the boot partition only after verification. The new runtime remains a trial
until the frozen recovery layer, application entry point, settings, Wi-Fi, and
authenticated portal start successfully. MQTT is deliberately outside the
update-health boundary so a broker outage remains locally repairable. Firmware
built with rollback enabled
returns to the previous partition if the trial cannot confirm itself.
The tile shows both the running firmware label and any staged firmware label.
During manual upload the portal reports browser upload, inactive-partition
writing, and read-back verification as separate stages. Only the active stage
appears beside the spinner; the supporting message lists completed stages.

The A/B Python application slots, settings, and certificates live in
the separate VFS partition and are not overwritten by base-firmware OTA. Keep
using `.hamd` for routine application changes; use `.hamf` when the frozen
recovery implementation must change. Credentials are independent of both and
remain in encrypted NVS. New production devices use the first-boot wizard;
there is no legacy root application or secrets bootstrap.

A `.hamu` combines one independently signed `.hamf` and one independently
signed `.hamd` with a third signed manifest that binds both component hashes,
versions, sizes, release sequences, activation order, maintenance requirement,
trial timeout and rollback policy. Build it after creating the matching
component bundles:

```sh
python3 tools/build_universal_update.py universal-1.5.0.hamu \
  --firmware ham-core-1.5.0.hamf \
  --application application-1.5.0.hamd \
  --version 1.5.0 --release-sequence 1500 \
  --signing-key ~/.ham-device/update.private-key
```

The portal streams and verifies both components and offers one activation and
reboot action. Already-installed components at the same or a newer sequence are
verified but skipped. Clean-seed v2 accepts HAMU format 2 only; legacy bridge
packages are deliberately rejected. Provision a complete v2 factory image on
new hardware rather than carrying an upgrade-only compatibility path.

### ESP32-S3 Migration Configuration

Start with the checked-in `examples/module_settings*.json` files for the
required module types.

The ESP32-S3 platform layer provides a single-pixel NeoPixel adapter for the
ESP32-S3-DevKitC-1 addressable RGB LED, publishes the detected runtime, and
enables firmware OTA only when an inactive ESP32 OTA partition is actually
present. Frozen `device_config.py` sets the status LED type to `neopixel` and,
for DevKitC-1 v1.1, uses GPIO38; a different physical board revision
requires a matching core build rather than a portal setting. Blue indicates
boot, Wi-Fi connection, or password processing;
the green heartbeat indicates healthy operation; blinking amber indicates a
module attention state (a failed `*_last_ok` status or populated
`*_last_error`); solid amber identifies the recovery service; and solid red
indicates a main application fault. The Grove AC driver configures ESP32 ADC attenuation; its
calibration must still be repeated against a trusted meter.

Validate hardware in this order: Wi-Fi/MQTT and HTTPS portal, one MAX31865 SPI
module, EMS UART timing/CRC, Grove AC ADC/calibration, then the optional OLED.
The example pin assignments are a starting point and must be checked against
the carrier wiring before energising attached equipment.

### Local Display

`display.py` provides a generic, extensible status display service. The current
driver supports 128x64 SH1107 displays connected over SPI. It is disabled by
default; enable it in the signed application `app_settings.json`:

```json
{
  "local_display": {
    "enabled": true,
    "type": "SH1107-SPI"
  }
}
```

Configure `spi`, `sck`, `mosi`, `cs`, `dc`, and `rst` for the target ESP32-S3
board and check them against all module pin assignments. New controller drivers
can be added to `DISPLAY_DRIVERS` without changing the display service.

When enabled, the display shows a compact status page with WiFi/MQTT state,
uptime, and recent alert count, then pages through current device payload
values. Module health details stay in the web portal; the OLED only shows a
module error when one is active. Short and long presses can page through
screens, request Home Assistant discovery, or toggle the runtime log level.

### Module Settings Files

Frozen `device_config.py` fixes the active filename as
`module_settings.json`. The file is user-owned and can be edited or loaded from
**Module > Configuration**.

If `module_settings.json` is absent, the device starts normally with zero
configured modules so configuration can be uploaded through the portal. An
installed file must contain valid JSON and pass module/ESP32 pin validation.

The repo includes example module configurations. Review and replace every pin
with a valid, non-conflicting ESP32-S3 GPIO before deployment:

| File | Sensor subclass | Purpose |
| --- | --- | --- |
| `examples/module_settings.whes.example.json` | `WHES` | WHES inverter RS485/Modbus setup |
| `examples/module_settings.ems.example.json` | `EMS-Boiler` | Worcester/Bosch EMS boiler broadcast monitor |
| `examples/module_settings.max31865_pt1000.example.json` | `MAX31865-PT1000` | PT1000 RTD probe through a MAX31865 amplifier |
| `examples/module_settings.grove_ac_voltage.example.json` | `Grove-AC-Voltage` | Grove MCP6002 AC voltage measurement and optional AC-present binary sensor |
| `examples/module_settings.dual_pt1000_voltage_display.example.json` | `MAX31865-PT1000`, `Grove-AC-Voltage` | Two PT1000 probes plus Grove AC voltage, intended for use with the local OLED display |

Copy the chosen example to `module_settings.json`, or load it through **Module >
Configuration**. The portal validator checks supported module types and pin or
shared-bus conflicts before applying and restarting.

Add `"retain_state": true` to a module if you want its state payload retained
by MQTT. This is useful for slow-changing values after a Home Assistant restart,
but it is intentionally opt-in.

For the combined PT1000/voltage/display example, load
`examples/module_settings.dual_pt1000_voltage_display.example.json` as the
module configuration and enable the display separately in signed
`app_settings.json`:

```json
{
  "local_display": {
    "enabled": true,
    "type": "SH1107-SPI"
  }
}
```

The two MAX31865 boards may share the ESP32-S3 SPI clock/data signals, but each
must use its own chip-select GPIO. Keep display, ADC, UART, status LED, and SPI
assignments distinct unless the validation rules explicitly allow sharing.

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
totals reset to `0` when the ESP32-S3 local date changes at midnight. NTP sync is
enabled in `HA-Device.py`, so make sure the device can reach one of the configured
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
the boiler bus and an ESP32-S3 UART; do not connect the UART directly to the
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

The example [examples/module_settings.ems.example.json](examples/module_settings.ems.example.json) uses
ESP32-S3 UART1 at 9600 baud, with TX on GPIO17 and RX on GPIO18. UART0 is
reserved for the console and is rejected by module validation. The example
includes common Greenstar 8000-style entities such as:

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
uses a shared SPI bus. Replace its legacy pin values with safe ESP32-S3 GPIOs
and give every MAX31865 a distinct chip-select pin.

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
board outputs a biased analogue AC waveform; the ESP32-S3 samples it with ADC,
removes the DC midpoint, calculates RMS, and applies a configurable calibration
multiplier.

The example [examples/module_settings.grove_ac_voltage.example.json](examples/module_settings.grove_ac_voltage.example.json)
uses ESP32-S3 ADC1 on GPIO1 and is aimed at typical 240V AC monitoring. It publishes:

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

The ESP32-S3 derives its raw hardware id from `machine.unique_id()`. The Home
Assistant/MQTT device id combines that raw id with the safe form of
the user-configured device name in encrypted NVS, for example
`fb1bd968b107ea19_htw`. This keeps entities separate when the same device is
reconfigured as a different logical device name.

Home Assistant presents the product as `Home Assistant Modular Device` by
`HAMD`, reports `ESP32-S3-DevKitC-1-N8R8` as its hardware platform, and uses
only the immutable raw hardware id as the device serial number. The composite
MQTT device id remains the discovery identifier and topic namespace.

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
used only the raw hardware id in discovery topics, set
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
- `recovery_boot.py`
- `app_update.py`
- `firmware_update.py`
- `hardware_platform.py`
- `update_security.py`
- `credential_security.py`
- `credential_store.py`
- `device_config.py`
- `factory_config.py`
- `portal_ui.py`
- `setup_wizard.py`
- `certificate_manager.py`
- `update_support.py`
- `wifi_recovery.py`
- `http_support.py`
- `HA-Device.py`
- `release_update.py`
- `app_settings.json`
- `component_versions.py`
- `module_settings.json`
- `settings_loader.py`
- `display.py`
- `web_portal.py`
- `web_portal_ui.py`
- `device_modules/`
- `lib/`
- any configured TLS certificate files

If the MicroPython filesystem is mounted on the host, the helper below copies the
runtime files and avoids caches/macOS metadata:

```sh
python3 tools/deploy.py /path/to/device-mount
```

ESP32-S3 boards normally expose a serial connection rather than a mounted
filesystem. Use the `mpremote` commands in
[docs/UPGRADE_GUIDE.md](docs/UPGRADE_GUIDE.md#3-installing-a-new-esp32-s3) for
the initial VFS deployment.

On production firmware, `main.py` prefers the frozen recovery supervisor and
uses the filesystem copy only if that frozen module is unavailable. The
supervisor selects the active application slot and runs `HA-Device.py` from it.

## Production Deployment Checklist

- Confirm the signed core uses the production watchdog value in
  `device_config.WATCHDOG_TIMEOUT_MS` (currently 60 seconds). This is immutable
  core policy, not a module or portal setting. Password verification services
  the watchdog while it runs.
- Let the device connect to MQTT and publish Home Assistant discovery once.
- Confirm Home Assistant shows these WHES entities:
  `serial_number`, `PV_p`, `battery_p`, `grid_p`, `home_p`, `battery_soc`,
  `pv_e`, `home_e`, `battery_charge_e`, `battery_discharge_e`,
  `grid_import_e`, `grid_export_e`, the WHES device information/running data
  sensors, and the RS485 diagnostic sensors.

## Recovery, release channels, and portal maintenance

When core recovery is requested, the device starts `HAMD-Recovery-xxxxxx` for
the configured timeout. Its WPA2 key is stored in encrypted NVS independently
of the normal portal password.
Browse to `http://192.168.4.1` to replace only the Wi-Fi SSID/password. Recovery
AP mode is suppressed during update trials so invalid trial credentials follow
the normal transactional rollback path.

The recovery service is also frozen into the core firmware. An exception before
the application becomes operational requests a clean reboot directly into the
core recovery console. A hung application is reset by the three-minute startup
deadline; two consecutive boots that miss the Wi-Fi health check enter recovery.
The console runs independently of `HA-Device.py`, requires the WPA recovery key
and a different password whose salted verifier is in encrypted NVS, and expires after 15 minutes before retrying normal
startup.

The core recovery console deliberately exposes only:

- Wi-Fi credential replacement;
- pending/staged application discard, activation, or rollback to the previous slot;
- signed `.hamd` application, `.hamf` core firmware, and `.hamu` combined
  upload/activation; and
- a normal application retry.

Remote recovery uploads are disabled unless `/.update-verification-key` is
provisioned, and protected bundles containing settings or certificates
are rejected. A pending application trial is rolled back before the console is
entered. A core firmware trial is confirmed only after Wi-Fi and the
authenticated portal start successfully; otherwise ESP-IDF retains control of
firmware rollback. Failures below the
MicroPython/network layer still require ESP-IDF rollback or USB flashing.

The portal exchanges a successful username/password login for an HttpOnly,
SameSite session cookie, supports explicit sign-out, uses CSRF-protected POST
actions, maintains upload-specific progress,
and exposes storage, slot, signing, recovery API, update history, manual app-slot
rollback, configuration validation, and sanitised diagnostic/config downloads.

The signed release endpoint is configured under `web_portal`. The selected
channel, disabled/daily/weekly check schedule, local check time, weekly day,
and automatic download/activation preferences are stored in encrypted user
settings and managed under **Maintenance > Upgrades**. Scheduled checking is
disabled by default; its time and day controls remain disabled until a relevant
schedule is selected:

```json
{
  "release_manifest_url": "https://updates.example/hamd/{channel}/latest.json"
}
```

MQTT broker trust, release-server trust, Syslog trust, and Device API client
trust use independent immutable paths in `device_config.py`. API client trust
is a bounded multi-CA directory. A device upgraded from RC1
continues to use the legacy shared CA for MQTT and release HTTPS until a
service-specific CA is installed. Each trust anchor can then be rotated by
itself under **Maintenance > Certificates**; the Device API never falls back to
the legacy anchor.

The endpoint returns a signed release descriptor containing the bundle type,
version, release sequence, HTTPS URL, exact byte size, SHA-256, compatibility
bounds, notes, and publication time. The device verifies the descriptor before
streaming the bundle, then independently verifies its size, hash, sequence, and
embedded bundle signature. HTTPS redirects and chunked transfer are supported;
redirects to non-HTTPS URLs are rejected. See `release_descriptor.schema.json`
for the host-side contract.

Create a static stable or beta channel tree with the same offline update key:

```sh
python3 tools/publish_release.py \
  --bundle application-1.5.0.hamd \
  --output-root release-site \
  --base-url https://updates.example/hamd \
  --channel stable \
  --notes "Universal HAMD runtime 1.5.0" \
  --signing-key ~/.ham-device/update.private-key
```

Upload `release-site/` to an HTTPS static host. The command refuses production
publication from a dirty worktree, verifies every signed bundle payload again,
requires its embedded build revision to match the publishing checkout, and
records that full Git revision in the signed release notes. The `--allow-dirty`
switch is intended only for
explicit development builds, which are marked `-dirty`. The command stores immutable
artifacts under `bundles/` and replaceable metadata under
`stable/latest.json` or `beta/latest.json`. Publish the application and core
firmware bundles to the same output root. The publisher retains one signed
release of each type in the channel index, allowing devices at different
application and firmware stages to use the same unchanged `latest.json`.
Each device filters all signed entries by its installed recovery/core API and
selects firmware first when its core is behind, then the applicable application
release. An incompatible application entry therefore cannot hide a compatible
core update. Automatic download and activation remain separate opt-in settings.

When a build places its `.hamd` or `.hamf` staging file directly in the
publisher's output root, successful publication removes that redundant source
after copying it into `bundles/`. Bundle inputs outside the output root are
never removed.

For first boot, `factory_config.py` may use a channel query endpoint or a static
template such as `https://updates.example/{channel}/latest.json`. A factory
bundle can offer device settings while leaving module settings absent.

## Host-Side Tests

The `tests/` directory contains a `unittest` suite for logic that can run
without microcontroller hardware:

```sh
python3 -m unittest discover -s tests
```

The tests cover application/core/universal updates, signatures and release
descriptors, encrypted backup/restore, credentials, certificates and API mTLS,
portal/setup workflows, timezone/DST scheduling and local-midnight WHES energy,
health/syslog/MQTT behavior, device drivers, Home Assistant discovery, shared
hardware helpers, and JSON configuration validation. CI also builds the complete
secure ESP32-S3 firmware and compiles every runtime module with pinned
MicroPython `mpy-cross`.

Device runtime files must also be compiled with the `mpy-cross` executable from
the pinned MicroPython v1.28.0 checkout. CPython `py_compile` is appropriate
only for `tools/` and `tests/`; it is not a substitute for MicroPython syntax
validation.

`app_settings.schema.json` and `module_settings.schema.json` can be
associated with `app_settings.json`, `module_settings.json`, and
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

- The code targets MicroPython on ESP32-S3. ESP32-S3-DevKitC-1-N8R8 is the
  supported board for direct HTTPS and base firmware OTA.
- ESP32 base firmware OTA requires an OTA partition table and a rollback-enabled
  initial firmware image; board type alone is not sufficient.
- MQTT discovery uses the `homeassistant/` topic prefix.
- Generated host bytecode/cache files are not needed on the ESP32-S3.
- Keep credentials and certificates out of public repositories.
- `.gitignore` excludes local secrets, certificates, bytecode, and macOS cache
  files.

## Safety and intended use

Home Assistant Modular Device is general-purpose monitoring and automation
software. It is not designed, tested, or certified for life-safety systems,
protective relaying, emergency shutdown, billing-grade energy measurement, or
other safety-critical applications.

Do not rely on this software as the sole means of preventing injury, equipment
damage, or property loss. Use appropriate independent safeguards. Installation
or modification of equipment connected to mains electricity must be performed
by a suitably qualified person in accordance with applicable regulations.
Measurements, alerts, and control actions may be delayed, inaccurate, or
unavailable because of hardware, software, configuration, network, or power
failures. Users are responsible for assessing suitability for their use.

## Licence

Copyright 2026 Ian Walton.

This project is licensed under the Apache License, Version 2.0. See
[`LICENSE`](LICENSE) for the complete terms. Third-party dependencies and
bundled components remain subject to their respective licences. See
[`SECURITY.md`](SECURITY.md) for private vulnerability reporting and
[`CHANGELOG.md`](CHANGELOG.md) for release history.
