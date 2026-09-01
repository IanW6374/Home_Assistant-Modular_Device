# MicroPython and firmware baseline

IoT-MD 2.5 beta uses MicroPython 1.29.0 at commit
`0fd6c573ea815774668bbb16b8e197c8822368b2`. The complete ESP32-S3 core is
built reproducibly with the project-owned board definition, frozen Python
manifest, native cryptography module, signed OTA wrapper and secure factory
image.

## Toolchain policy

The qualified toolchain remains ESP-IDF 5.5.1 at commit
`fcae32885b0296b32044cb99ecbdc50d98dddb83`. MicroPython 1.29 recommends
ESP-IDF 5.5.2 and supports 5.5.1. Keeping the existing IDF patch release avoids
changing two major runtime dependencies in the same device release. The exact
MicroPython and ESP-IDF revisions are enforced by `firmware/build-lock.json`.

ESP-IDF 6 is not used for v2.5. MicroPython 1.29's ESP32 port requires the
supported IDF 5 family, and the v2.5 transport changes must be qualified against the
already proven runtime. An IDF 6 toolchain belongs in a separate future alpha
after an upstream MicroPython release supports that pairing.

The board uses MicroPython's ESP32-S3 SPIRAM base configuration together with
the `SPIRAM_OCT` variant. The base fragment enables PSRAM-backed allocation;
the variant selects the octal bus mode. Production builds reject a generated
configuration unless PSRAM boot initialisation, malloc integration, and octal
mode are all enabled.

## Validation result

The v2.4 production-security build was validated with secure boot, flash
encryption, encrypted NVS, the IoT-MD native cryptography module and the frozen
application manifest enabled. The resulting OTA application image is
1,445,888 bytes, or 68.9% of the 2 MiB OTA partition. This is below both the
80% warning level and the 85% release failure threshold. A future ESP32 USB NCM
core will require a fresh size/security and hardware qualification before
promotion.

## Adopted benefits

The baseline receives MicroPython 1.29's maintenance and security updates,
including its newer mbedTLS and LittleFS revisions, ESP32 fixes and runtime
improvements. No administrator-visible feature is enabled solely because the
runtime exposes a new API; new capabilities remain subject to the normal
security, storage and hardware qualification process.

## v2.4 capability adoption

The v2.4 native `_iotmd_platform` module provides a bounded RTC no-init memory
record because the qualified ESP32-S3 MicroPython build does not expose a
standard backup-memory API. The Python platform layer will prefer a future
standard runtime API when available. The record contains only boot counters,
stage, state, reset/update status and heap observations; CRC validation rejects
undefined content after power loss, and atomic flash state remains available.

## v2.5 capability adoption

The v2.5 application records whether `network.USBD_NCM` exists, but does not
treat that symbol as sufficient platform support. It keeps the NCM data path
inactive under the default signed feature policy. MicroPython 1.29's generic
implementation is not yet integrated with the ESP32 port's network locking,
NIC registration and TinyUSB APIs, so the qualified ESP32-S3 board keeps
`MICROPY_PY_NETWORK_USBD_NCM` disabled and reports the capability unavailable.
It remains optional and is not part of trial-confirmation health.

MicroPython v1.29.0 is the current release baseline; a future v1.30 cannot be
treated as providing ESP32 NCM until its ESP32 port is built and exercised on
hardware. ESP-IDF 6 alone would not supply the missing MicroPython integration,
and it is outside the IDF 5 versions supported by the v1.29 ESP32 port. Any IDF
6 migration must therefore be a separate alpha with full TLS, storage, USB,
boot and update requalification.

When a compatible core becomes available, the transport will assign a
deterministic `169.254.x.1` link-local device address and serve DHCP to the USB
host. The implementation does not perform RFC 3927 collision detection, which
is why the feature remains experimental and must not be treated as an ordinary
LAN interface.

MicroPython 1.29 exposes no stable SSL-session object through its uasyncio
connection API. v2.5 introduces only an opaque `TLSSessionHandle` seam. Release
and TLS-syslog clients accept it but perform a full handshake; capability output
correctly reports session resumption unavailable.

## Opportunities retained for later qualification

- USB NCM can provide an authenticated maintenance path after the beta firmware,
  host compatibility and recovery interaction have completed qualification.
- Native modules declared from manifests may simplify selected performance
  work, but the existing explicit native-module build remains easier to audit.

These are opportunities rather than commitments. They must not be inferred as
available device features until they appear in a release changelog and the
relevant operations documentation.
