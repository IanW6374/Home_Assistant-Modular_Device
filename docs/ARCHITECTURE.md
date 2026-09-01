# IoT-MD v2 architecture

IoT-MD v2 is a clean-seed ESP32-S3 platform. Dependencies point inward:

```text
frozen platform -> application domain <- services <- portal/API/MQTT/display
                                               ^
                                               |
                                      runtime composition
```

## Frozen platform

The signed core owns boot supervision, watchdog recovery, Secure Boot, flash
encryption, credential storage, TLS primitives, update verification, OTA
partitions and first-run setup. It can recover a device when the replaceable
application is absent or unhealthy.

The v2.4+ boot coordinator records forward-only startup stages in a compact,
CRC-protected record. Optional RTC no-init memory preserves the latest stage
across software and watchdog resets; an atomic flash checkpoint remains the
authoritative fallback. See [Boot lifecycle and activation health](BOOT_LIFECYCLE.md).

Wi-Fi remains the required production interface. The v2.5 application contains
an optional USB NCM transport contract, but the current ESP32-S3 core reports
the capability unavailable; it does not replace Wi-Fi setup or recovery. CI
rejects excessive core-slot use.

## Application and services

The application domain owns module contracts, resource allocation, state,
commands, diagnostics, events and configuration semantics. Services expose
these use cases without depending on HTTP, MQTT or display transports.

Drivers declare logical GPIO, ADC, UART, SPI and chip-select requirements before
setup. The central resource manager maps those names to physical resources,
enforces ownership, caches compatible shared instances and supplies an
owner-scoped injection interface. Exclusive resources cannot have multiple
owners; shared buses must use compatible electrical configuration. Legacy
drivers remain supported while they migrate to injected construction.

`ApplicationContext` is the runtime service registry. Its supervisor owns
background tasks and routes critical failures into device health.

## Transports

The portal, Device API, MQTT and local display consume application services.
`APIRequest` and `APIResponse` contain no socket or Wi-Fi types; the Device API
router owns authentication, scope and domain dispatch while the HTTPS adapter
owns HTTP parsing, mTLS and stream lifetime. A listener bound to all IP
interfaces can therefore serve Wi-Fi or qualified Ethernet/USB interfaces
without changing the API contract. The portal and API retain independent TLS
listeners because their identity and authorization models differ. Portal routes
declare their required role; API v2 requires mutual TLS and scoped client
certificates.

USB NCM is an experimental `NetworkTransport`. The interface can activate only
when signed policy, beta channel and runtime capability all permit it. The
current ESP32-S3 core deliberately reports that capability unavailable pending
an upstream-compatible port. It is never a boot or update dependency. See
[Feature flags and transports](FEATURES_AND_TRANSPORTS.md).

The capability matrix deliberately distinguishes native USB device hardware,
NCM-capable hardware, the runtime API symbol, ESP32-port compatibility,
firmware build inclusion and effective IoT-MD availability. In particular,
`hasattr(network, "USBD_NCM")` is diagnostic input rather than an enablement
decision.

Large inventory remains available for compatibility, but new clients should
use the bounded device, interface, hardware, service and configuration
projections. Central feature flags are decided from signed policy, build
availability, channel and capability—not from a version string.

The portal may use a publicly trusted certificate for its public DNS name.
Device API/fleet, MQTT, Syslog and release connections remain private-CA
services. Public portal replacement cannot change the independent API server
identity. See [Certificate identities](CERTIFICATES.md).

## Upgrades and persistence

All update transports use one transaction model:

```text
upload -> verify -> stage -> activate -> trial -> confirm
                         |                 |
                         +------ rollback-+
```

Application, core and universal installers are bounded adapters. Structured
events feed logs, audit, health, update progress, syslog and fleet telemetry.
Persistent records are versioned, transactional and bounded.

Trial confirmation is a local health decision. Required platform memory,
configuration, local network, repair portal and watchdog facilities must be
ready. External dependencies such as MQTT, NTP, Home Assistant and remote
syslog may place the device in `degraded` state but cannot by themselves roll
back a repairable device.

## Verification

Production changes must pass host tests, MicroPython compilation, schema,
documentation, accessibility and architecture checks, secure core builds and
hardware qualification covering TLS, storage pressure, interrupted updates,
watchdog recovery, trial confirmation and rollback.
