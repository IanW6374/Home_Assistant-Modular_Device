# IoT Modular Device (IoT-MD)

IoT-MD v2 is production firmware for secure, modular ESP32-S3 devices. One
device can host multiple sensors, switches and energy interfaces while exposing
a web portal, configurable MQTT messaging and a versioned HTTPS API. Home
Assistant is an optional built-in integration rather than a transport
requirement.

## Highlights

- Secure Boot v2, flash encryption and encrypted credential storage.
- Signed application, core and universal upgrades with anti-rollback, trial
  activation, health confirmation and recovery.
- Responsive HTTPS portal with administrator, operator and viewer roles.
- Platform-neutral MQTT topics, optional Home Assistant discovery and
  mandatory-mTLS `/api/v2` access.
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
- MicroPython 1.29.0 built with ESP-IDF 5.5.1.
- Python 3.12 or newer for host tooling.
- ESP-IDF and the pinned MicroPython checkout for core builds.

The shipping partition layout provides dual secure core slots and a separate
encrypted application filesystem. Bluetooth, PPP and Ethernet are excluded
from the production core to preserve recovery capacity.

## First boot

Production devices are seeded with a signed factory image and a unique setup
password. Connect to the `IoT-MD-Setup-xxxxxx` Wi-Fi network, browse to
`http://192.168.4.1`, enter that password and complete the wizard.

The wizard configures:

1. device identity, Wi-Fi and network mode;
2. portal administrator credentials;
3. an administrator-selected certificate method: **Automatic IoT CA
   enrollment**, **IoT CA enrollment authorization (`.iotenroll`)**, **Private CA ACME
   enrollment**, **Manual certificate package**, or **Self-signed device certificate**; and
4. signed application installation and restart.

After setup, open the configured portal DNS name on port 8443. The device also
retains its `.local` mDNS name for private services. The Device API uses port
8444 by default and requires an enrolled client CA and certificate.

## Portal

The portal provides:

- status, module values and diagnostics;
- network, portal, time, Messaging, API and logging settings;
- module configuration, calibration and debug controls;
- users and role-aware permissions;
- application, core and universal upgrades;
- certificates, ACME, backup/restore, health history, device/audit logs, and
  non-destructive restart, shutdown or factory reset controls.

Settings that require a restart are committed immediately and collected behind
one banner action so several changes can be activated with one reboot.

## Messaging and Home Assistant

MQTT base and state/command/response/availability topics are administrator
defined. The optional Home Assistant profile publishes discovery records that
refer to those same operational topics. Broker TLS verifies the exact hostname
configured under **System > Messaging** against the certificate DNS/IP SAN;
the installed MQTT CA establishes trust but does not replace that identity
check. Retained module state is an MQTT broker feature, not persistence of
physical output state across a device restart. See the
[messaging guide](docs/MESSAGING.md).

Fleet and release services are provided by the separate public
[IoT-MD Management Suite](https://github.com/IanW6374/HA-IoT-MD-Management-Suite).
The generic IoT Certificate Authority and IoT Syslog remain independent
add-ons. See the [management ecosystem](docs/MANAGEMENT_SUITE.md).

## Updates

IoT-MD uses three signed artifact types:

| Extension | Purpose |
| --- | --- |
| `.iotapp` | Replaceable application and selected drivers |
| `.iotcore` | Secure MicroPython core firmware |
| `.iotuni` | Matched application and core universal update |

Use **Maintenance > Upgrades** for normal installation. Release sequences must
increase monotonically. Verification occurs before staging, and activation uses
trial health checks with rollback support. Automatic checks can be disabled or
scheduled daily/weekly in device-local time, independently of automatic
download and activation.

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
| `iotmd.py` | Small recovery-compatible application bootstrap |
| `iotmd_runtime.py` | Runtime composition and supervision; precompiled in production bundles |
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
- [MicroPython and firmware baseline](docs/MICROPYTHON.md)
- [Certificate identities and initial provisioning](docs/CERTIFICATES.md)
- [MQTT messaging and Home Assistant](docs/MESSAGING.md)
- [Device API v2](docs/API.md) and [OpenAPI contract](docs/openapi.yaml)
- [Management ecosystem](docs/MANAGEMENT_SUITE.md)
- [Upgrade and recovery](docs/UPGRADE_GUIDE.md)
- [Fleet protocol](docs/FLEET_PROTOCOL.md)
- [Security operations](docs/SECURITY_OPERATIONS.md)
- [Module guide](docs/modules/README.md)
- [Qualification records](docs/qualification/README.md)
- [Security reporting](SECURITY.md)
- [Changelog](CHANGELOG.md)

Licensed under Apache-2.0.
