# Home Assistant Modular Device (HAMD)

HAMD v2 is production firmware for secure, modular ESP32-S3 devices integrated
with Home Assistant. One device can host multiple sensors, switches and energy
interfaces while exposing a web portal, MQTT discovery and a versioned HTTPS
API.

## Highlights

- Secure Boot v2, flash encryption and encrypted credential storage.
- Signed application, core and universal upgrades with anti-rollback, trial
  activation, health confirmation and recovery.
- Responsive HTTPS portal with administrator, operator and viewer roles.
- MQTT/Home Assistant discovery plus mandatory-mTLS `/api/v2` access.
- Encrypted complete configuration backup and validated restore preview.
- NTP, IANA time zones, daylight-saving support and local-time energy resets.
- Structured audit, health and update history with local and remote syslog.
- Resource-aware modular drivers with persistent calibration and diagnostics.

## Supported modules

| Category | Drivers |
| --- | --- |
| Sensors | DHT11, HCSR04, Grove AC Voltage, MAX31865 PT1000 |
| Energy and HVAC | WHES, EMS Boiler, RS485 Modbus, multiport Modbus |
| Outputs | On/off and dimmer switches; on/off, brightness and RGB lights |

See the [module guide](docs/modules/README.md) for wiring, configuration,
entities and diagnostics for every supported module type. Complete example
configurations are in [`examples/`](examples/).

## Hardware and software

- ESP32-S3-DevKitC-1-N8R8 with 8 MB flash, 8 MB octal PSRAM and Wi-Fi.
- MicroPython 1.28.0 built with ESP-IDF 5.5.1.
- Python 3.12 or newer for host tooling.
- ESP-IDF and the pinned MicroPython checkout for core builds.

The shipping partition layout provides dual secure core slots and a separate
encrypted application filesystem. Bluetooth, PPP and Ethernet are excluded
from the production core to preserve recovery capacity.

## First boot

Production devices are seeded with a signed factory image and a unique setup
password. Connect to the device setup Wi-Fi network, browse to
`http://192.168.4.1`, enter that password and complete the wizard.

The wizard configures:

1. device identity, Wi-Fi and network mode;
2. portal administrator credentials and HTTPS identity;
3. MQTT/Home Assistant connectivity;
4. signed application installation and restart.

After setup, open `https://<device-name>.local:8443/`. The Device API uses port
8444 by default and requires an enrolled client CA and certificate.

## Portal

The portal provides:

- status, module values and diagnostics;
- network, portal, time, MQTT, Home Assistant, API and logging settings;
- module configuration, calibration and debug controls;
- users and role-aware permissions;
- application, core and universal upgrades;
- certificates, ACME, backup/restore, health history, logs and factory reset.

Settings that require a restart are committed immediately and collected behind
one banner action so several changes can be activated with one reboot.

## Home Assistant

MQTT discovery is the normal entity integration. The optional fleet manager is
published separately as
[HAMD Home Assistant Add-ons](https://github.com/IanW6374/HAMD-Home-Assistant-Addons).
Add that repository URL in Home Assistant to install the ingress dashboard for
inventory, health, policy and staged rollout management.

## Updates

HAMD uses three signed artifact types:

| Extension | Purpose |
| --- | --- |
| `.hamd` | Replaceable application and selected drivers |
| `.hamf` | Secure MicroPython core firmware |
| `.hamu` | Matched application and core universal update |

Use **Maintenance > Upgrades** for normal installation. Release sequences must
increase monotonically. Verification occurs before staging, and activation uses
trial health checks with rollback support.

See the [upgrade guide](docs/UPGRADE_GUIDE.md) for release and USB recovery
procedures.

## Configuration and backup

Runtime policy is stored in `app_settings.json`; hardware modules are defined in
`module_settings.json`. Their JSON schemas are
[`app_settings.schema.json`](app_settings.schema.json) and
[`module_settings.schema.json`](module_settings.schema.json).

The portal can export ordinary configuration or a password-encrypted complete
backup containing credentials, certificates and trust material. Complete
backups remain sensitive and should be stored as securely as device keys.

## Development

Install host dependencies and run the complete validation suite:

```sh
python3 -m pip install -r requirements-dev.txt
python3 tools/check_repository_hygiene.py
python3 tools/check_documentation.py
python3 tools/validate_json_schemas.py
python3 tools/check_accessibility.py
python3 tools/check_architecture.py
python3 tools/check_micropython_compat.py
python3 -m unittest discover -s tests -v
```

Important entry points:

| Path | Responsibility |
| --- | --- |
| `HA-Device.py` | Runtime composition and supervision |
| `application/` | Transport-neutral state and service contracts |
| `services/` | Application use cases |
| `device_modules/` | Drivers, capabilities and resource allocation |
| `web_portal.py` | Authenticated portal transport |
| `device_api.py` | Mandatory-mTLS API v2 transport |
| `firmware/` | Frozen-core manifest and partition configuration |
| `tools/` | Build, signing, qualification and recovery tooling |
| `tests/` | Host unit and contract tests |

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Upgrade and recovery](docs/UPGRADE_GUIDE.md)
- [Fleet protocol](docs/FLEET_PROTOCOL.md)
- [Security operations](docs/SECURITY_OPERATIONS.md)
- [Module guide](docs/modules/README.md)
- [Qualification records](docs/qualification/README.md)
- [Security reporting](SECURITY.md)
- [Changelog](CHANGELOG.md)

Licensed under Apache-2.0.
