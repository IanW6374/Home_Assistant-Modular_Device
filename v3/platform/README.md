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

The first bootable alpha will start the platform, publish the capability
contract, start an embedded MicroPython runtime and remain recoverable with no
v3 application installed.
