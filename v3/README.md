# IoT-MD v3 greenfield alpha

This directory is the isolated starting point for the v3 architecture rewrite.
Stable v2.5 maintenance continues from `main`; v3 development continues on
`alpha/v3-platform-rewrite` until its own promotion gates pass.

Version `3.0.0-alpha.8` retains the native ABI 4 boundary and improves the
manual upgrade and Wi-Fi selection experience. Alpha 7 added guarded
OTA trial controls, native boot/recovery state ahead of the replaceable product,
and a fixed-capacity asynchronous job/event boundary. These are implemented
mechanisms, not completed qualification claims: paired trial, native rollback,
recovery and job qualification remain false until their hardware tests pass.
The proven v2.5 product runtime remains the active compatibility payload.

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
[roadmap](../docs/V3_ROADMAP.md) before adding implementation code. The
[Alpha 7 test note](../docs/V3_ALPHA7.md) defines its exact scope and safe test
procedure. The [Alpha 6 note](../docs/V3_ALPHA6.md),
[Alpha 5 note](../docs/V3_ALPHA5.md),
[Alpha 4 note](../docs/V3_ALPHA4.md),
[Alpha 3 note](../docs/V3_ALPHA3.md),
[Alpha 2 note](../docs/V3_ALPHA2.md) and
[Alpha 1 note](../docs/V3_ALPHA1.md) retain the preceding boundary history.

Validate the initial contract scaffold with:

```sh
python3 v3/tools/check_contracts.py
```
