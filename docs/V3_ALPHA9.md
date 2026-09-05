# IoT-MD v3.0.0-alpha.9 test note

## Purpose

Alpha 9 implements the next three greenfield integration gates: native physical
resource management, production-facing v3 transport adapters and production
identity integration. It remains an alpha mechanism release. The active device
continues to use the v2.5 compatibility runtime while the new paths are tested
in isolation and shadow mode.

## Included

- Native platform ABI 5 constructors for GPIO, ADC, UART, I2C and SPI.
- Exclusive ownership for GPIO, ADC and UART; I2C/SPI sharing only when both the
  declared signature and effective native configuration match.
- Native GPIO interrupt ownership, bounded interrupt events, deterministic
  release, stale-claim reset after a MicroPython restart and physical
  peripheral recovery after a driver failure.
- Runtime configuration contract version 4 with bounded physical parameters and
  non-mutating migration of version 3 resources to safe exclusive defaults.
- Production lifecycle adapters for Wi-Fi/reconnection, MQTT/Home Assistant,
  HTTPS portal, mTLS Device API and syslog.
- A production identity adapter which reads the installed certificate
  inventory, dispatches established enrollment and renewal operations, and
  generation-guards trust removal.
- Stable opaque certificate/key handles whose internal locator mapping is held
  in encrypted transactional NVS. Certificate and key paths do not enter v3
  snapshots or APIs.

## Expected behavior

The installed portal and device behavior should remain compatible with Alpha 8.
The release qualification view should report platform ABI 5. Resource
capabilities should show the five physical mechanisms as present and
`qualified` as false. Paired trial, native rollback, independent recovery and
native-job qualification also remain false.

The new production adapters must not create a second live listener or duplicate
MQTT/Home Assistant publications while the compatibility runtime owns the
device. Their initial use is contract testing and controlled shadow comparison.

## Suggested hardware observations

1. Confirm an exclusive duplicate GPIO/UART/ADC claim fails before either
   module can start.
2. Confirm two I2C or SPI owners with the same signature and effective settings
   share one bus; change one effective setting and confirm construction fails.
3. Exercise a GPIO edge, confirm one bounded `resource-interrupt` event, then
   release the owner and confirm no further event is emitted.
4. Inject one peripheral failure, confirm the ESP-IDF driver is rebuilt, and
   repeat after a MicroPython service restart.
5. In shadow mode compare Wi-Fi, MQTT, portal, Device API and syslog state with
   the compatibility implementation without binding duplicate sockets.
6. Exercise each managed enrollment method, renewal failure/retry and stale
   trust-removal generation. Confirm support/API output contains no paths,
   certificate bytes or private-key material.

## Safety and rollback

The release sequence is `2714`. Use
`universal-3.0.0-alpha.9.iotuni` for complete application/core version pairing.
Do not set resource, transport or identity qualification evidence to passed
from a successful install alone. The compatibility runtime and existing frozen
recovery path remain the recovery baseline.
