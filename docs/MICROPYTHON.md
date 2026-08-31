# MicroPython and firmware baseline

IoT-MD 2.3 uses MicroPython 1.29.0 at commit
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

The board uses MicroPython's ESP32-S3 SPIRAM base configuration together with
the `SPIRAM_OCT` variant. The base fragment enables PSRAM-backed allocation;
the variant selects the octal bus mode. Production builds reject a generated
configuration unless PSRAM boot initialisation, malloc integration, and octal
mode are all enabled.

## Validation result

The production-security build has been validated with secure boot, flash
encryption, encrypted NVS, the IoT-MD native cryptography module and the frozen
application manifest enabled. The resulting OTA application image is
1,445,888 bytes, or 68.9% of the 2 MiB OTA partition. This is below both the
80% warning level and the 85% release failure threshold.

## Adopted benefits

The baseline receives MicroPython 1.29's maintenance and security updates,
including its newer mbedTLS and LittleFS revisions, ESP32 fixes and runtime
improvements. No administrator-visible feature is enabled solely because the
runtime exposes a new API; new capabilities remain subject to the normal
security, storage and hardware qualification process.

## Opportunities retained for later qualification

- USB networking could provide a field-recovery transport, but it is not
  enabled because it changes the device attack surface and USB recovery model.
- Backup-memory support could retain small diagnostic breadcrumbs across some
  resets, but it is not used for secrets or authoritative state and needs
  reset-cause qualification first.
- Native modules declared from manifests may simplify selected performance
  work, but the existing explicit native-module build remains easier to audit.

These are opportunities rather than commitments. They must not be inferred as
available device features until they appear in a release changelog and the
relevant operations documentation.
