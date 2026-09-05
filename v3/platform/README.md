# Native ESP-IDF platform

The platform is a purpose-built ESP-IDF application which embeds the qualified
MicroPython runtime. It owns mechanisms that must remain available when the
replaceable application is absent or broken:

- secure boot, flash encryption and hardware identity;
- watchdog, reset reason, boot stages and recovery selection;
- encrypted NVS, credential handles and filesystem mounting;
- OTA partition selection, signed staging, trial confirmation and rollback;
- Wi-Fi, native USB and future Ethernet interface drivers;
- monotonic time, heap/PSRAM, flash and hardware-resource observations; and
- the bounded `_iotmd_platform` ABI exposed to MicroPython.

Platform code must not know about portal routes, MQTT topics, Home Assistant,
fleet policy, module semantics or presentation. Native operations which can
block are represented as jobs and publish completion through the platform event
queue. Secret key material is referred to by opaque handles and is never
returned to MicroPython.

ABI 4 retains encrypted transactional namespaces and owner-scoped resource
claims, then adds guarded OTA trial observation/control, encrypted native boot
and recovery state, and a fixed four-job/eight-event worker boundary. Jobs are
non-blocking at submission, expose structured error/retryability information and
declare a five-second operation limit. The mechanisms compile into the secure
core, but paired trial, rollback, recovery and job qualification remain false
until the applicable HIL gates pass. Recovery is independent of replaceable
product code; it still relies on the signed frozen MicroPython core.
