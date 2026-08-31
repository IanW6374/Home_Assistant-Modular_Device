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

The v2.4 boot coordinator records forward-only startup stages in a compact,
CRC-protected record. Optional RTC no-init memory preserves the latest stage
across software and watchdog resets; an atomic flash checkpoint remains the
authoritative fallback. See [Boot lifecycle and activation health](BOOT_LIFECYCLE.md).

The production build is Wi-Fi-only and CI rejects excessive core-slot use.

## Application and services

The application domain owns module contracts, resource allocation, state,
commands, diagnostics, events and configuration semantics. Services expose
these use cases without depending on HTTP, MQTT or display transports.

Drivers declare GPIO, ADC, UART, SPI and chip-select requirements before setup.
Exclusive resources cannot have multiple owners; shared buses must use
compatible electrical configuration.

`ApplicationContext` is the runtime service registry. Its supervisor owns
background tasks and routes critical failures into device health.

## Transports

The portal, Device API, MQTT and local display consume application services.
The portal and API retain independent TLS listeners because their identity and
authorization models differ. Portal routes declare their required role; API v2
requires mutual TLS and scoped client certificates.

The portal may use a publicly trusted certificate for its public DNS name.
Device API/fleet, MQTT, Syslog and release connections remain private-CA
services. Public portal replacement cannot change the independent API server
identity. See [Certificate identities](CERTIFICATES.md).

## Updates and persistence

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
