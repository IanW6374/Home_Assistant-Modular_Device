# IoT-MD v3.0.0-alpha.5 test note

## Purpose

Alpha 5 introduces the greenfield identity, fleet and v2-migration domain
boundaries and ports the supported v2.5 driver catalog to the multi-resource
driver contract. It builds on the successfully installed Alpha 4 transports.
The proven v2.5 compatibility runtime remains the active product entry point
while the new services complete hardware and interoperability qualification.

## Included

- Runtime configuration contract version 3 with explicit identity and fleet
  services, bounded dependency declarations, multi-resource modules and
  non-mutating migration from configuration versions 0, 1 and 2.
- Certificate lifecycle orchestration for all five supported enrollment
  methods. Certificate and private-key material stays behind opaque integer
  handles; only bounded identity metadata crosses the platform boundary.
- Managed renewal for every non-manual method, clock-aware scheduling and
  generation-guarded removal of MQTT, release, Syslog, private-CA and API-client
  trust anchors.
- Bounded fleet inventory/canary reports and signed policy validation with
  target, time, signature, replay and rollout-pause enforcement. Device API v3
  exposes dedicated `fleet:read` and `fleet:write` routes.
- Previewed v2 complete-backup migration. Staged credentials, module settings
  and certificates use opaque handles in a separate v3 namespace and are
  activated only after a healthy v3 trial; an unhealthy trial discards them.
- A static catalog covering all 11 supported v2.5 driver backends and 13 module
  type variants. Drivers claim all declared resources before the injected
  hardware backend starts and release their owner scope after failure or stop.
- Server-rendered identity, fleet and migration summaries which contain no
  secrets and preserve the Alpha 4 transport-independent presentation model.

## Deliberately incomplete

- The Alpha 5 platform adapters are testable contracts, not yet the active
  production certificate store, fleet client or v2 restore path.
- Real certificate enrollment/renewal, signed Management Suite policy exchange,
  representative v2 backup migration and the production driver backends still
  require HIL evidence.
- Native paired partition selection, atomic activation of staged migration
  handles, rollback and USB NCM remain capability-gated until their respective
  platform tests pass.

## Safety and rollback

The release sequence is `2710`. Install only on a recoverable test device.
Returning to an older sequence can require USB recovery or a later signed
release with a higher sequence. Alpha 5 does not mutate confirmed v2 state.

## Hardware and integration checks

1. Upload and activate the universal package. Confirm the portal returns and
   reports application/core version `3.0.0-alpha.5`.
2. Confirm existing portal, MQTT and Device API behavior remains unchanged,
   because the v2.5 compatibility product runtime remains active.
3. Exercise the identity adapter with a test certificate set. Confirm managed
   methods renew only with a synchronized clock, manual packages never renew,
   and support output contains handles and metadata but no key bytes.
4. Apply a correctly signed, targeted and current fleet policy through a
   `fleet:write` client; confirm a `fleet:read` client receives the bounded
   report and repeated failed canary outcomes pause the rollout.
5. Preview a representative authenticated v2 complete backup, stage it, force
   one failed v3 trial and confirm rollback leaves the original v2 backup and
   state unchanged. Retry and confirm the staged v3 handles only after health.
6. Exercise each supported driver backend on representative hardware,
   including a multi-resource driver, resource conflict and failed-start
   cleanup.

The Alpha 5 exit gate additionally requires representative v2 devices to
migrate, roll back and retry without losing confirmed v2 state.
