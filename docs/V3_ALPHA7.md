# IoT-MD v3.0.0-alpha.7 test note

## Purpose

Alpha 7 implements the next three greenfield platform gates: guarded native OTA
trial control, recovery which does not load replaceable product code, and a
bounded native job/event boundary. It also corrects the Alpha 6 native-module
registration defect and makes Safari's sign-in verification state consistent.

This is a mechanism test release. Capability fields continue to report
`paired_trial`, `native_rollback`, recovery qualification and job qualification
as false until the corresponding device tests pass.

## Included

- Platform ABI 4 OTA snapshots with running/next partition labels, image state,
  and guarded confirmation or rollback eligibility.
- Confirmation and rollback calls bound to the caller-observed running label,
  preventing a stale operation from acting after the active partition changes.
- An encrypted native recovery record advanced by the frozen supervisor before
  replaceable product imports. Explicit recovery and three consecutive
  incomplete normal boots select the signed frozen recovery path.
- A fixed four-entry native job queue and eight-entry event queue for recovery,
  update confirmation and update rollback. Submission is non-blocking; events
  expose bounded status, numeric errors, retryability and detail, with a
  declared five-second operation limit.
- Release Qualification diagnostics showing native update state and separating
  available mechanisms from HIL-qualified production claims.
- A firmware build invariant requiring `_iotmd_crypto`, `_iotmd_platform` and
  `_iotmd_platform_v3` to be both compiled and registered in MicroPython.
- Stable Safari sign-in feedback rendered before credential submission.

## Deliberately incomplete

- Application-slot confirmation and the native core trial are not yet one
  atomic native transaction; paired trial and native rollback remain unqualified.
- Product-independent recovery still runs in the signed frozen MicroPython core.
  It is not a bare-ESP-IDF recovery environment for a corrupted confirmed core.
- Native recovery and job mechanisms are not production-qualified until the
  controlled reset, watchdog, rollback, queue-saturation and power tests pass.
- Credential, certificate, migration and networking jobs remain future ABI work.
- USB NCM remains unavailable on the ESP32-S3 MicroPython v1.29 production core.

## Safety and rollback

The release sequence is `2712`. Install the universal artifact on a recoverable
test device. Alpha 7 changes the frozen core and requires the full
`universal-3.0.0-alpha.7.iotuni`; an application-only update cannot repair an
Alpha 6 core whose v3 native module was omitted from the import table.

Returning to an older sequence may require USB recovery or a newer signed
release with a higher sequence. The v2.5 compatibility runtime remains active,
and confirmed v2 configuration is not mutated.

## Initial checks

1. Upload and activate `universal-3.0.0-alpha.7.iotuni`.
2. Confirm application and core both report `3.0.0-alpha.7`.
3. Open **Maintenance > Release qualification** and confirm that the native
   boundary is available rather than showing “native v3 platform is unavailable”.
4. Confirm the running partition/state are populated and recovery/job mechanisms
   show available while their qualification values remain **Not qualified**.
5. Sign out and in several times in Safari; **Securely verifying…** should be
   rendered consistently after submitting the form.
6. Exercise explicit recovery, repeated incomplete boot, watchdog, trial
   confirmation, trial rollback and queue saturation only with serial monitoring
   and a known USB recovery path.
7. Record observed results in the release-specific qualification record. Do not
   set a capability qualification flag merely because the method is importable.

