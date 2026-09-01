# IoT-MD v3 greenfield alpha

This directory is the isolated starting point for the v3 architecture rewrite.
It is not a device release and must not produce an artifact accepted by the v2
stable channel. Stable v2.5 maintenance continues from `main`; v3 development
continues on `alpha/v3-platform-rewrite` until its own promotion gates pass.

The rewrite keeps the proven product requirements while establishing the
native ESP-IDF platform and MicroPython application boundary before porting
features. Existing v2 code is reference behavior, not a source tree to move
wholesale.

## Directory ownership

| Directory | Owner |
| --- | --- |
| `platform/` | Native ESP-IDF platform, boot, storage, update and hardware adapters |
| `runtime/` | MicroPython kernel, services, modules and user-facing adapters |
| `contracts/` | Versioned data exchanged across the native/runtime boundary |
| `host/` | Build, migration, signing, qualification and factory tooling |
| `tools/` | Alpha-only static and contract checks |

## Non-negotiable rules

1. Native code never imports application policy; MicroPython never manipulates
   OTA partitions, encrypted NVS internals or bootloader state directly.
2. Boundary values are bounded primitive data with a declared schema and ABI
   version. Raw ESP-IDF or MicroPython objects do not cross the boundary.
3. The operator installs one paired universal release. Platform and runtime
   components remain independently signed and independently recoverable.
4. A failed platform/runtime trial rolls back the pair.
5. Hardware capability, firmware inclusion, runtime integration and signed
   product policy are reported separately.
6. No v2 configuration is mutated until a v3 trial is confirmed. Migration is
   previewable, transactional and reversible.
7. Every alpha milestone has host, hardware-in-the-loop and recovery gates.

Read the [target architecture](../docs/V3_ARCHITECTURE.md),
[requirements](../docs/V3_REQUIREMENTS.md) and
[roadmap](../docs/V3_ROADMAP.md) before adding implementation code.

Validate the initial contract scaffold with:

```sh
python3 v3/tools/check_contracts.py
```
