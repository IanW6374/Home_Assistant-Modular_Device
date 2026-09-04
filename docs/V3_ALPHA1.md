# IoT-MD v3.0.0-alpha.1 test note

## Purpose

Alpha 1 proves that an independently versioned native ESP-IDF capability
boundary can coexist with the current MicroPython product runtime and paired
upgrade mechanism. It is a bootable architecture test, not the completed v3
rewrite.

## Included

- Native `_iotmd_platform_v3` module with ABI version 1.
- One bounded `capabilities()` result covering board, MicroPython runtime,
  actual secure-boot/flash-encryption state, encrypted-NVS build state, PSRAM,
  running OTA partition size and interface gates.
- MicroPython `Platform` adapter which rejects missing, unknown, inconsistent or
  unsupported native values.
- Executable JSON Schema, checked-in example and host contract tests.
- The normal signed application, core and firmware-first universal test
  artifacts.

## Deliberately retained from v2.5

- MicroPython 1.29.0 and ESP-IDF 5.5.1 build baseline.
- Existing boot/recovery/update implementation.
- Existing portal, API, MQTT, certificate, fleet and module runtime.
- Existing v2 configuration namespace and driver API.

This compatibility payload lets hardware testing isolate the new native/runtime
boundary. It must not be interpreted as completion of the greenfield runtime
port.

## Safety and rollback

The test release uses sequence `2706`, which is newer than stable v2.5.0
sequence `2705`. Install only on a recoverable test device. The ordinary update
anti-rollback policy will reject a lower-sequence stable bundle; returning the
device to v2.5.0 may therefore require the USB recovery/factory workflow or a
later stable maintenance release with a newer sequence.

USB NCM remains unavailable. Alpha 1 does not change device configuration,
partition layout, network behavior or certificate material.

## Hardware verification

After the universal trial is confirmed, verify the normal portal and then use
the USB REPL:

```python
import _iotmd_platform_v3
from v3.runtime.iotmd_next.platform import Platform

print(_iotmd_platform_v3.ABI_VERSION)
print(Platform().capabilities())
```

Expected essentials are ABI 1, target `esp32-s3`, runtime `micropython`, PSRAM
present, Wi-Fi present and `usb_ncm_available` false. On a production-provisioned
device, secure boot and flash encryption should report true.

Record boot, restart, portal, update confirmation, rollback and recovery
results before advancing the Alpha 1 gate.
