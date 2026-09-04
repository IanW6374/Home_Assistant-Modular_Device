# IoT-MD v3 target architecture

## Status

This document defines the greenfield architecture under development on
`alpha/v3-platform-rewrite`. It is not the v2.5 runtime architecture and does
not change the stable release contract.

## Design objective

IoT-MD v3 is a secure embedded platform which hosts a replaceable MicroPython
product runtime. Native ESP-IDF code owns durable platform mechanisms;
MicroPython owns product policy and modular behavior. The boundary is explicit,
versioned, bounded and testable on the host.

```text
ESP32-S3 ROM/eFuses
        |
ESP-IDF secure platform
  boot | storage | OTA | network | USB | crypto | watchdog
        |
  _iotmd_platform ABI + bounded event queue
        |
MicroPython application kernel
  config | health | resources | modules | certificate policy
        |
domain services
  messaging | portal | API | fleet | diagnostics | upgrades
        |
transport/presentation adapters
  HTTPS | MQTT | syslog | display | qualified USB/Ethernet
```

## Native platform responsibilities

The native platform remains useful with no MicroPython application installed.
It owns secure boot and recovery selection, hardware identity, encrypted NVS,
filesystem mounting, watchdog state, OTA partitions, update verification,
paired trial/rollback state, native network interfaces and hardware capability
reporting. It exposes secret handles, never private key bytes.

Native code implements mechanism only. It does not know portal navigation,
MQTT topics, Home Assistant entities, module meaning, fleet rollout rules or
certificate enrollment policy.

## MicroPython runtime responsibilities

The runtime owns versioned configuration, service composition, module
contracts, driver behavior, health interpretation, portal/API/MQTT adapters,
certificate enrollment policy, fleet behavior and presentation. Its domain
services do not depend on sockets, HTTP or ESP-IDF types.

The runtime can request a native job and observe its result through a bounded
event record. It cannot select OTA partitions, write encrypted NVS internals,
extract keys or keep raw native pointers.

## Platform ABI

ABI 1 established capability discovery. ABI 2 added bounded encrypted-storage
handles and atomic whole-namespace snapshots. ABI 3 adds owner-scoped logical
resource claims and bounded resource inventory. The ABI follows these rules:

- primitive values only: bounded strings, integers, booleans, bytes and maps;
- explicit maximum size and timeout for every call;
- opaque integer handles for secrets and long-lived native resources;
- no silent fallback when a capability or ABI version is unavailable;
- structured error code, operation, retryability and diagnostic context;
- capability discovery separate from feature enablement; and
- backwards compatibility within one major ABI, with additive optional fields.

An Alpha 2 namespace commit writes a CRC-protected generation to the inactive
of two NVS snapshot slots and commits it before it can supersede the prior
generation. The runtime supplies the generation it read, so concurrent or
stale commits fail rather than overwrite newer state. Recovery validates both
slots and chooses the newest complete generation. Payloads are capped at 4096
bytes and native handles—not ESP-IDF NVS objects—cross the boundary.

The checked-in JSON schemas are executable documentation for host tooling. The
native module and runtime adapter will share generated constants or one source
definition where practical.

## Application kernel

The Alpha 3 kernel validates or previews migration before it creates a service
or claims hardware. Its registry resolves service dependencies deterministically
and its cooperative supervisor isolates transient failures as degraded state,
records a bounded event, and permits an individual service restart. A failed
boot stops every started service and releases owner-scoped claims before it
enters recovery.

The initial reference sensor is deliberately small: it proves the driver,
resource and lifecycle contracts without making a production claim for a new
physical sensor. Its sample source is injectable for host and HIL fixtures.
Alpha 4 registers product transports through the same dependency-aware service
registry. Configuration contract version 2 declares adapter identity,
dependencies and criticality; socket or client instances are injected at the
outer edge and never enter configuration or support snapshots.

MQTT receives only a bounded state projection and provides a separate optional
Home Assistant discovery operation. The server-rendered portal and Device API
share bounded request/response values while retaining distinct authentication:
the portal uses roles and the API requires a verified mTLS identity with an
explicit scope. Navigation and form fields come from shared metadata rather
than duplicated page definitions.

Connectivity diagnostics rotate one bounded probe at a time across DNS, time,
TLS, MQTT, CA, syslog and release services. They report operational state and
the exception class only. This preserves useful fault isolation without
turning a support snapshot into a credential or endpoint-detail export.

Kernel health and support snapshots have fixed collection limits and contain
only operational state. Runtime configuration and module settings are excluded
so these snapshots cannot become an accidental secret-export path.

## Release and recovery model

Users install one universal release containing independently signed platform
and runtime components plus an outer pairing manifest. The device has confirmed
and trial state for both layers. Confirmation is atomic from the product's
perspective: failure of either required layer rolls the pair back.

The frozen/native recovery path accepts signed v3 releases, reports diagnostics
and restores a confirmed pair without importing the product runtime. Separate
component artifacts remain available for factory and recovery workflows, not as
the ordinary operator upgrade sequence.

The paired state contract distinguishes `staging`, `ready`, `trial`,
`confirmed` and `rollback`. Alpha 2 persists and validates this state but does
not yet delegate OTA partition selection or rollback to the new native ABI;
those capabilities remain false until hardware interruption testing proves the
complete mechanism.

## Configuration migration

V3 has a new configuration namespace and schema. Importing a v2 encrypted
backup produces a preview, validation report and migration plan. The confirmed
v2 state remains untouched until v3 trial health succeeds. Rollback therefore
returns to both the v2 software and its original configuration.

## Hardware and resource model

Drivers request logical resources. The runtime resource service checks product
policy while the native platform owns physical GPIO, ADC, UART, I2C, SPI and
interrupt allocation. Compatible shared buses use one native instance; unsafe
conflicts fail before a driver starts.

ABI 3 implements the exclusive ownership ledger for ADC, GPIO, I2C, SPI and
UART identities. Claims use opaque integer handles, are idempotent for the same
owner, conflict across different owners, and can be released individually or
by owner after a failed start or MicroPython soft restart. Physical peripheral
construction and explicitly shared-bus policy remain later platform work.

The initial target remains ESP32-S3 N8R8. A future production board should
prefer 16 MB flash and 8 MB PSRAM, but larger hardware must not become an alpha
prerequisite until partition and migration policy are decided.

## Security invariants

- Production secure boot, flash encryption and encrypted NVS are mandatory.
- Release, fleet-policy and certificate trust domains use distinct keys.
- Portal and private-service identities remain independent.
- Device API access remains mutual TLS with registered fingerprint and scope.
- Recovery cannot accept unsigned code or bypass credential policy.
- Debug and alpha capability cannot be enabled by a runtime symbol alone.

The initial decisions are recorded in
[ADR-0001](adr/0001-v3-hybrid-platform.md) and
[ADR-0002](adr/0002-v3-paired-release.md).
