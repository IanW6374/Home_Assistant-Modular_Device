# Boot lifecycle and activation health

IoT-MD v2.4 uses an explicit boot contract shared by the frozen recovery core
and replaceable application. The existing A/B application slots, dual OTA core
partitions and universal-update coordinator remain authoritative for selection,
confirmation and rollback.

## Stages

The boot record advances through these bounded stages:

1. `reset`
2. `platform`
3. `persistent-state`
4. `update-reconcile`
5. `filesystem`
6. `configuration`
7. `certificates`
8. `hardware`
9. `network`
10. `portal`
11. `essential-services`
12. `health-check`
13. `running`

`safe-mode` is a terminal diagnostic stage rather than a normal forward
transition. Every stage records the current and minimum observed free heap.

## Persistent record

The record contains its format version, boot, checkpoint-generation and failure
counters, incomplete and healthy flags, last stage, device state, reset cause,
paired-update state, heap observations and a bounded failure reason. The
generation counter selects the newest valid RTC or flash copy even when one
medium failed during the preceding checkpoint. The record never contains
credentials, private keys, tokens, configuration values or certificate
contents.

The custom ESP32-S3 firmware stores a CRC-protected copy in a 768-byte RTC
no-init region that survives software and watchdog resets. Power loss may leave
that region undefined, so its magic, format and CRC are always validated. An
atomic `.boot-state.json` checkpoint is retained as the fallback and durable
record.

## Device states

The transport-neutral lifecycle reports one of:

- `booting`
- `initialising`
- `running`
- `degraded`
- `safe`
- `restarting`
- `updating`

The portal, API inventory and support bundle consume this same state instead of
deriving independent interpretations.

## Trial activation gates

An application/core trial is confirmed only after:

- the ESP32-S3 exposes the expected PSRAM-backed heap;
- free MicroPython heap is above the activation floor;
- the home network is connected;
- the authenticated repair portal is listening when enabled; and
- the configured watchdog is operational.

The production N8R8 target requires at least 4 MiB of detected PSRAM, 1 MiB free
heap before application loading and 512 KiB at activation. These floors detect
the known internal-RAM-only firmware failure while leaving normal operational
headroom.

MQTT, NTP, Device API, Home Assistant, fleet and remote-syslog availability
depend on external systems or time. Failure of one of these services is
reported as `degraded`; it does not roll back an otherwise locally repairable
device.

## Failure policy

Update trials retain the aggressive two-unhealthy-boot rollback threshold.
Normal operation allows three incomplete boots before entering the frozen core
recovery console. Application exceptions, capability failures and health-gate
failures preserve the last stage, heap and bounded reason for USB, portal and
support-bundle diagnosis.

## Toolchain boundary

v2.4 remains pinned to MicroPython 1.29.0 and ESP-IDF 5.5.1. Changing the SDK
major version during boot qualification would combine independent sources of
failure. ESP-IDF 6 evaluation is reserved for a future MicroPython alpha branch
after upstream support and a separate hardware qualification campaign exist.
