# HAMD v2 alpha architecture

## Release intent

`2.0.0-alpha.1` is a deliberately breaking development release. The single
test device may be factory-reseeded from the retained v1.9 production image;
v1.9 configuration and backup compatibility is not an alpha acceptance gate.
The v2 formats are nevertheless versioned so a compatibility policy can be
established before v2 stable.

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

The existing `HA-Device.py` and `web_portal.py` entry points are retained while
code moves behind these interfaces. Characterisation tests protect observable
behavior during each extraction.

## Versioned contracts

- Driver API: version 2. Drivers publish metadata, configuration schema,
  capabilities, diagnostics and standard health callbacks.
- Event API: version 2. Events carry an identifier, UTC epoch, severity,
  component, correlation identifier, message and bounded structured values.
- Device API: `/api/v2` exposes inventory, health, support and fleet-policy
  resources over mandatory mTLS. Existing v1 resources may remain during the
  alpha only when they cost no additional runtime state.
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
