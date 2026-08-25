# IoTMD v2 architecture

IoTMD v2 is a clean-seed ESP32-S3 platform. Dependencies point inward:

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

## Verification

Production changes must pass host tests, MicroPython compilation, schema,
documentation, accessibility and architecture checks, secure core builds and
hardware qualification covering TLS, storage pressure, interrupted updates,
watchdog recovery, trial confirmation and rollback.
