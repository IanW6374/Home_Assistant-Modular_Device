# HAMD v2 architecture

HAMD v2 is a clean-seed platform. New devices are provisioned from a complete
signed image; runtime compatibility with v1 application layouts and state files
is not an architectural requirement.

## Dependency direction

```text
immutable platform -> application domain <- application services <- transports
                                               ^
                                               |
                                      runtime composition root

external fleet service -> versioned mTLS device API -> application services
```

Dependencies point inward. Portal, API, MQTT, display, and fleet transports do
not manipulate hardware, update files, credentials, or health persistence
directly. They call application services assembled by the composition root.

## Immutable platform

The frozen core owns boot supervision, watchdog recovery, Secure Boot and flash
encryption integration, encrypted credential storage, trust roots, TLS
primitives, signed update verification, OTA partitions, and first-run setup.
It must remain able to recover a device when the replaceable application is
missing or unhealthy.

The immutable platform may depend on ESP-IDF/MicroPython facilities but never on
portal pages, Home Assistant discovery, fleet presentation, or a particular
device driver.

The shipping ESP32-S3 profile is Wi-Fi-only. Bluetooth/NimBLE, PPP and SPI
Ethernet are excluded, the native build is size-optimised, and CI rejects a
core image at 85% OTA-slot occupancy. This keeps the dual 2 MiB core slots and
3.875 MiB encrypted application filesystem balanced without relying on a
partition change. Repartitioning remains a clean-seed factory operation and is
considered only if the minimal core cannot remain below that budget.

## Application domain

The application domain owns versioned module contracts, resource allocation,
commands, state, diagnostics, structured events, configuration semantics, and
update transaction states. Domain code is transport-neutral and bounded for
ESP32-S3 memory and flash constraints.

Module drivers declare hardware resources before setup. Exclusive resources
such as GPIO, ADC channels, UARTs, and chip-select pins cannot have multiple
owners. Shared buses are accepted only when their electrical configuration is
identical.

## Application services

Services expose use cases to all transports:

- module inventory, state, diagnostics, and commands;
- network status, scans, and network-trial confirmation;
- MQTT/Home Assistant publication;
- structured events, health, audit, and telemetry sinks;
- update upload, verification, staging, activation, and progress;
- configuration and certificate administration;
- fleet policy and bounded remote commands.

The `ApplicationContext` is the only runtime service registry. Background work
is owned by its task supervisor so failures are observable and critical task
failures enter the device health boundary.

## Transport adapters

The authenticated portal, mTLS API, MQTT, and local display have independent
transport policy but share application services. Portal routes are registered
with an explicit role and controller. Rendering consumes view models and must
not contain persistence or hardware operations.

The portal and API retain separate TLS listeners because they have different
identity and authorization models. Their HTTP parsing and response primitives
may be shared.

## Updates

Every update enters one transaction coordinator:

```text
source -> resumable artifact -> verify -> stage -> activate -> trial
                                                       |          |
                                                       +-- rollback/confirm
```

Application, firmware, and universal installers remain separate platform
adapters. Upload sessions, progress, error reporting, cleanup, audit, and
transaction status are shared. A transport never invokes an installer
directly.

## Events and persistence

Operational logging, audit, health, update progress, syslog, MQTT diagnostics,
and fleet telemetry begin as structured events. Sinks independently decide
format and retention. Persistent device repositories use versioned,
transactional, bounded records; partial writes must be recoverable.

## Fleet service

Fleet management is independently versioned from device firmware. The Home
Assistant add-on uses SQLite repositories, durable jobs, idempotent commands,
bounded event retention, and per-device backoff. It never holds the release or
Secure Boot signing keys; fleet policy uses its own trust domain.

## Verification gates

Changes must pass CPython unit/contract tests, MicroPython compilation and API
compatibility checks, schema/documentation/accessibility checks, and hardware
qualification for boot, storage pressure, TLS, interrupted update, watchdog,
trial confirmation, and rollback paths.
