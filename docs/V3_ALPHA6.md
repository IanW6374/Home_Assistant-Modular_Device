# IoT-MD v3.0.0-alpha.6 test note

## Purpose

Alpha 6 is the greenfield integration and qualification release. It adds the
cutover decision boundary and makes every remaining promotion claim explicit,
persistent and visible. The v2.5 compatibility runtime remains the active
product path. Alpha 6 cannot select active-v3 mode while native paired trial
and rollback capabilities are false or any evidence gate is open.

## Included

- A release-bound qualification ledger in encrypted transactional storage.
  Evidence automatically starts fresh when version or release sequence changes.
- Fifteen explicit gates: soak, health, storage, network recovery, certificate
  renewal, paired upgrades, power recovery, canary health, release confirmation,
  native recovery, watchdog recovery, identity interoperability, fleet
  interoperability, migration rollback and all 13 supported driver variants.
- A colour-coded summary on **Status > Overview**, full observed versus required
  state under **Maintenance > Release qualification**, and a bounded projection
  in Device API and support output.
- A host qualification runner which persists interrupted campaigns and supports
  mTLS monitoring plus explicit controlled-test event recording.
- A fail-closed cutover coordinator with compatibility, shadow and active modes.
  Failed v3 boot or runtime health invokes recovery and returns to compatibility.
- Stable universal-upload component wording and more conservative post-restart
  portal readiness detection based on two complete sequential responses.

## Deliberately incomplete

- Host and unit tests validate gate behavior, persistence and failure paths;
  they are not substitutes for the listed physical observations.
- `paired_trial` and `native_rollback` remain false in the ESP32-S3 platform
  capability record. Consequently active-v3 cutover remains blocked.
- USB NCM remains an optional future transport and is not a stable promotion
  requirement for this MicroPython v1.29 ESP32-S3 build.
- A gate remains `not-run` until its controlled test is observed. Failed
  evidence remains sticky until an operator deliberately resets the campaign.

## Safety and rollback

The release sequence is `2711`. Install only on a recoverable test device.
Returning to an older sequence can require USB recovery or a later signed
release with a higher sequence. Alpha 6 does not mutate confirmed v2 state and
does not enable active-v3 ownership.

## Initial checks

1. Upload and activate `universal-3.0.0-alpha.6.iotuni`.
2. Confirm both application and core report `3.0.0-alpha.6`.
3. Open **Maintenance > Release qualification**. Untested physical gates must
   show `not-run`, never passed.
4. Confirm the Overview summary is **In progress** or **Not started**, not
   **Ready**.
5. Confirm portal, MQTT, Device API, Syslog, modules and certificate renewal
   continue operating through the compatibility runtime.
6. Run controlled qualification using the commands in the upgrade guide.
7. Validate exported evidence against the qualification evidence schema.

Promotion to Beta remains prohibited until all physical, interoperability,
migration, recovery and soak evidence is captured and native paired
trial/rollback has passed its independent hardware matrix.
