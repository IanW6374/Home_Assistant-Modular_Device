# IoT-MD v3.0.0-alpha.2 test note

## Purpose

Alpha 2 introduces the first native transactional-storage mechanism and an
executable paired platform/runtime lifecycle. It also carries two minor fixes
identified while qualifying Alpha 1: visible update-verification progress and
correct Management Suite signing-key installation.

This remains an architecture test containing the v2.5 compatibility runtime.
It does not claim completion of the Alpha 2 exit gate.

## Included

- Native `_iotmd_platform_v3` ABI 2.
- Up to four opaque encrypted-NVS namespace handles.
- A maximum 4096-byte namespace snapshot stored in alternating CRC-protected
  generations with compare-and-swap conflict detection.
- A fail-closed MicroPython storage adapter.
- A paired-release state machine for stage, ready, trial, confirm and rollback
  transitions, with exact platform/runtime version and SHA-256 identities.
- Executable capability and paired-state JSON Schemas.
- Host interruption tests at both sides of every persistent state transition.
- Asynchronous portal finalisation so update verification can be polled while
  it is running.
- A distinct validated transaction for the Management Suite signing key.

## Deliberately incomplete

- The new ABI does not yet select native OTA partitions, start a pair trial or
  execute native rollback. `paired_trial` and `native_rollback` report false.
- Existing v2.5 recovery/update code remains responsible for installing this
  test release.
- Hardware power-cut qualification is not replaced by host interruption tests.
- USB NCM remains capability-gated off.

## Safety and rollback

The release sequence is `2707`. Install only on a recoverable test device.
Returning to an older sequence can require USB recovery or a later release
with a higher sequence.

## Hardware checks

After installation, confirm normal portal operation and verify through USB:

```python
import _iotmd_platform_v3
from v3.runtime.iotmd_next.platform import Platform

platform = Platform()
print(_iotmd_platform_v3.ABI_VERSION)
print(platform.capabilities())
```

Expected essentials are ABI 2, encrypted and transactional storage true,
`max_namespaces` 4, `max_payload_bytes` 4096, `paired_manifest` true,
`paired_trial` false and `native_rollback` false.

In the portal, upload an application, firmware or universal artifact and check
that verification advances above 0%. Then install a valid Management Suite
signing key and confirm that the transaction succeeds without the certificate
path error. Record any restart, rollback or storage fault before advancing the
Alpha 2 gate.
