# HAMD v2 alpha architecture

## Release intent

`2.0.0-alpha.8` is a deliberately breaking clean-seed development release.
Devices receive a complete v2 factory image; v1.9 configuration, API and
universal-update compatibility are intentionally excluded. The v2 formats
remain versioned so a compatibility policy can be frozen before v2 stable.

The alpha is accepted only when its device runtime, Home Assistant fleet
add-on, release tooling, documentation, host tests and one-device hardware
qualification all pass from a clean source revision.

## Device service boundaries

The boot module remains a composition root. New behavior belongs in one of the
following services and is injected through a narrow interface:

| Service | Responsibility | Must not own |
| --- | --- | --- |
| `NetworkService` | station lifecycle, cached scans, NTP and network trials | portal rendering, MQTT discovery |
| `ModuleRuntime` | driver creation, polling, commands and state snapshots | transport authentication |
| `MessagingService` | MQTT lifecycle, discovery and bounded publishing | module hardware access |
| `PortalService` | route dispatch, forms, sessions and page adapters | device orchestration globals |
| `UpdateService` | upload sessions, verification, staged activation and rollback | release signing keys |
| `FleetService` | inventory, signed policy, maintenance windows and rollout state | firmware writes |
| `EventService` | structured audit/health events and support snapshots | page-specific formatting |

`HA-Device.py` remains the composition root and `web_portal.py` is the embedded
HTTP request controller. Application state, task ownership, driver resources,
route policy, view models and update orchestration live behind explicit,
enforced interfaces. Characterisation tests protect observable behavior.

Alpha.8 physically separates the formerly embedded implementation clusters:

- portal HTTP/authentication helpers, presenters, live views and settings views;
- setup-wizard HTTP control, provisioning workflow and HTML views;
- certificate wire codecs from certificate lifecycle management;
- credential schema validation from encrypted persistence;
- application slot storage from bundle verification and activation;
- Modbus register codecs from bus transport; and
- Home Assistant discovery from boot and hardware coordination.

`tools/check_architecture.py` enforces dependency direction, retired clean-seed
compatibility markers, and line/function ceilings for the remaining composition
and transport roots. Limits may be lowered as further code is extracted; raising
one requires an explicit architecture review recorded in this document.

## Versioned contracts

- Driver API: version 2. Drivers publish metadata, configuration schema,
  capabilities, diagnostics and standard health callbacks.
- Event API: version 2. Events carry an identifier, UTC epoch, severity,
  component, correlation identifier, message and bounded structured values.
- Device API: `/api/v2` exclusively exposes modules, operations, inventory,
  health, support and fleet-policy resources over mandatory mTLS.
- Fleet policy: format 1, ECDSA P-256 signed, monotonically sequenced and bound
  to a device or named cohort.
- Configuration: format 4. Alpha imports reject unsupported formats clearly;
  selective restore validates every selected section before changing state.
- Universal update: HAMU format 2 binds its components, required activation
  order, maintenance policy and rollback behavior in the outer signature.

## Portal security model

Portal identities are stored as bounded records with one of three roles:

- `administrator`: all configuration, security, update and reset operations.
- `operator`: diagnostics, logs, module commands and approved update actions.
- `viewer`: overview, diagnostics, health and logs only.

Every route declares its minimum role. Sessions are independent per login,
expire individually, use CSRF tokens unrelated to session identifiers and are
invalidated when their user is disabled or its password changes.

## Fleet and Home Assistant add-on

The add-on stores no device private keys. Its fleet-policy signing key is a
separate management trust domain and is never reused for release signing or
Secure Boot. Each device is registered with its
mTLS client identity and public metadata. The add-on provides inventory,
health, audit events, maintenance windows, rollout cohorts, failure-rate stops,
signed-policy distribution and rollback requests. A one-device installation
uses the same model as a larger fleet.

The initial UI is served by the add-on and is suitable for ingress. Device
state is exposed to Home Assistant through MQTT discovery and add-on API
endpoints; management credentials remain in add-on protected storage.

## Release and quality gates

- Host unit and parser-fuzz suites pass.
- Desktop/mobile HTML passes structural accessibility checks.
- Application, core and universal artifacts verify independently.
- SBOM and provenance documents accompany the artifacts.
- The production core is size-optimised, contains no Bluetooth/NimBLE, PPP or
  SPI-Ethernet support, warns at 80% OTA occupancy and fails at 85%.
- The core image remains below the configured hard OTA threshold.
- The connected ESP32-S3 completes the one-device qualification plan,
  including interrupted staging, rollback/recovery, mTLS, backup, DST and
  local-midnight checks where supported by the fixture.
- API latency, minimum heap, scan latency, image size and flash checkpoints are
  recorded as release baselines rather than unbounded observations.

## Explicitly deferred from alpha

Support for boards other than ESP32-S3-DevKitC-1-N8R8, Matter, and executable
third-party driver downloads are excluded. They require separate hardware and
security threat models and are not prerequisites for a useful fleet add-on.
