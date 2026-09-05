# IoT-MD v3 alpha roadmap

Milestones are capability gates, not calendar commitments. A milestone cannot
advance because its version label exists; its listed evidence must pass.

## Alpha 0 — architecture and contracts

- Approve requirements, native/runtime ownership and security invariants.
- Establish executable ABI schemas and alpha-only CI.
- Select the MicroPython and ESP-IDF evaluation matrix without changing v2.
- Define partition, paired-release and v2 rollback constraints.

Exit: contract checks pass and architecture decisions are accepted.

## Alpha 1 — recoverable native platform

- Boot a minimal secure ESP-IDF platform on ESP32-S3 N8R8.
- Expose ABI/version/capability and bounded boot-health records.
- Embed MicroPython without loading a product runtime.
- Enter recovery and install a signed test platform after runtime failure.

Exit: repeated boot, watchdog, corrupt-runtime and recovery HIL tests pass.

Current status: `3.0.0-alpha.1` implements the first native capability ABI and
validated MicroPython adapter on the qualified v2.5 toolchain. It is a boundary
test candidate, not completion of the Alpha 1 exit gate; native recovery
ownership and its HIL fault matrix remain to be implemented.

## Alpha 2 — storage and paired updates

- Implement encrypted namespace handles and transactional storage.
- Implement paired native/runtime staging, trial, confirmation and rollback.
- Build one universal host artifact with SBOM and provenance.
- Prove power-interruption recovery at every update transition.

Exit: no interruption produces an unrecoverable or unconfirmed mixed pair.

Current status: `3.0.0-alpha.2` implements ABI 2 encrypted transactional
namespace snapshots and the runtime paired-release state machine. Host tests
cover interruption at every state-record transition. Native partition-pair
trial selection, automatic rollback and the corresponding hardware power-cut
matrix remain open; capability reporting therefore continues to mark paired
trial and native rollback unavailable.

## Alpha 3 — application kernel and one reference module

- Add configuration schema/migrations, service registry and task supervisor.
- Add resource allocation across the platform ABI.
- Port one simple sensor as the reference driver and contract-test fixture.
- Expose bounded health, event and support snapshots.

Exit: the reference module survives restart, configuration failure and resource
conflict tests without compromising recovery.

Current status: `3.0.0-alpha.3` implements ABI 3 owner-scoped resource claims,
an exact versioned configuration and migration preview, the first application
kernel/service supervisor, a reference sensor driver, and bounded health/event/
support snapshots. Host tests cover restart, invalid configuration, exclusive
resource conflict, failure isolation and cleanup. Physical sensor exercise,
watchdog fault injection and repeated hardware restart qualification remain the
Alpha 3 HIL evidence gate.

## Alpha 4 — product transports

- Port MQTT, server-rendered portal and mTLS Device API over Wi-Fi.
- Generate portal forms/navigation from shared metadata.
- Add unified DNS/time/TLS/MQTT/CA/syslog/release connectivity diagnostics.
- Keep service contracts independent of transport adapters.

Exit: portal/API/MQTT behavior and security match the v3 requirements baseline.

Current status: `3.0.0-alpha.4` implements configuration contract version 2,
dependency-ordered product services, bounded request/response values, injected
Wi-Fi, MQTT, server-rendered portal and mTLS Device API adapters, shared
presentation metadata and unified connectivity diagnostics. Host tests cover
role/scope enforcement, escaping, payload bounds, service ordering and
diagnostic redaction. The v2.5 compatibility runtime remains the active network
stack until MQTT/portal/API parity and network-fault HIL evidence passes.

## Alpha 5 — identity, fleet and v2 migration

- Port certificate enrollment/renewal and trust administration.
- Add fleet inventory, signed policy and canary reporting.
- Import a v2 complete backup through previewed transactional migration.
- Port the supported v2.5 driver set through the reference driver contract.

Exit: representative v2 devices migrate, roll back and retry without losing
their confirmed v2 state.

Current status: `3.0.0-alpha.5` implements configuration contract version 3,
opaque certificate/key handles, managed identity renewal, generation-guarded
trust administration, signed targeted fleet policy, bounded canary reporting,
previewed and isolated v2 complete-backup migration, and the complete v2.5
driver catalog over a multi-resource lifecycle contract. Host tests cover
validation, replay/time/target rejection, renewal policy, rollout pausing,
secret-free migration previews, rollback and driver cleanup. Real certificate
issuance, Management Suite interoperability, representative backup migration,
physical drivers and power-interruption recovery remain the Alpha 5 HIL gate.

## Alpha 6 — integration cutover and executable qualification

- Persist release-bound evidence for every outstanding promotion gate.
- Surface compact qualification state in the portal, Device API and support
  workflow, while retaining detailed machine-readable evidence.
- Add compatibility, shadow and active runtime ownership with fail-closed
  preflight and recovery fallback.
- Provide resumable host tooling for soak, network, renewal, paired-upgrade,
  power, native/watchdog recovery, interoperability, migration and driver HIL.

Exit: active-v3 cutover is possible only after native paired trial/rollback and
all 15 observed qualification gates pass. Failed or unexecuted tests must not be
represented as successful.

Current status: `3.0.0-alpha.6` implements and enforces the gate ledger,
installed portal/API/support projections, host campaign runner and cutover
coordinator. Active-v3 remains correctly blocked because native paired trial
and rollback are not yet qualified and the hardware campaign is not yet run.

## Alpha 7 — native recovery and job boundary

- Observe and guard native OTA trial confirmation and rollback by the expected
  running partition.
- Persist native boot attempts and recovery requests before replaceable product
  code is loaded, while preserving explicit factory-reset precedence.
- Add a fixed-capacity asynchronous native job/event boundary for recovery and
  OTA trial operations with bounded arguments, errors and diagnostics.
- Make module registration a build invariant and surface native mechanism and
  qualification state separately in Release Qualification.

Exit: signed universal installation exposes ABI 4 on hardware; corrupt/missing
product, repeated incomplete boot, watchdog and OTA trial tests recover through
the frozen core; queue saturation remains bounded; and controlled confirm and
rollback tests produce correct events without selecting the wrong partition.

Current status: `3.0.0-alpha.9` retains these mechanisms and host contracts.
The `paired_trial`, `native_rollback`, native recovery and native job
qualification flags intentionally remain false pending the Alpha 7 HIL matrix.
This release does not claim bare-ESP-IDF recovery from a corrupted confirmed
MicroPython core; bootloader A/B rollback and USB disaster recovery remain the
lower-level safeguards.

## Alpha 9 — physical resources, production transports and identity

- Advance the native boundary to ABI 5 with GPIO, ADC, UART, I2C and SPI
  construction, safe I2C/SPI sharing, interrupt cleanup and peripheral rebuild.
- Advance runtime configuration to version 4 with bounded physical parameters,
  explicit sharing and non-mutating migration from version 3.
- Bridge Wi-Fi, MQTT/Home Assistant, HTTPS portal, mTLS Device API and syslog
  implementations into the transport-independent v3 services.
- Bridge the installed certificate/trust stores and managed enrollment methods
  into v3 identity records backed by persistent opaque handles.

Exit: the complete physical-driver matrix passes conflict, shared-bus,
interrupt, failure and soft-restart tests; network fault tests establish service
parity; and every enrollment/renewal/trust method passes recovery and
interoperability tests without exposing key material.

Current status: `3.0.0-alpha.9` implements and host-tests the mechanisms and
compiles ABI 5 into the production-secure ESP32-S3 core. Resource,
transport-adapter and identity qualification remain open until HIL and shadow
parity evidence is recorded. The v2.5 compatibility runtime therefore remains
active, and none of these mechanisms change the still-unqualified Alpha 1–2
paired-update or independent-recovery gates.

## Beta — operational qualification

- Multi-day soak, storage pressure, certificate renewal and network fault tests.
- Repeated production-secure universal upgrades and power interruption.
- Fleet canary rollout and automated pause on health thresholds.
- Documentation, accessibility, API and support workflows complete.

Stable promotion requires reproducible clean-source artifacts, complete HIL
evidence and no dependency on an experimental transport.
