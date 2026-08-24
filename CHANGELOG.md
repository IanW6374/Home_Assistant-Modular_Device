# Changelog

## 2.0.1 - 2026-08-24

### Fixed

- Stream universal `.hamu` upgrades directly into the transactional installers
  instead of caching the complete container on constrained device storage.
- Reclaim superseded or unfinishable resumable uploads automatically and reject
  uploads that cannot fit before they consume the remaining filesystem space.

## 2.0.0 - 2026-08-24

HAMD v2 is the first production release of the clean-seed ESP32-S3 platform.

### Added

- Secure first-boot provisioning, encrypted credentials, Secure Boot and flash
  encryption.
- Role-aware web portal, MQTT discovery and mandatory-mTLS API v2.
- Modular resource contracts, diagnostics and persistent calibration.
- Signed application, core and universal updates with resumable uploads,
  progress, trial activation, health confirmation and rollback.
- Time-zone/DST scheduling, local-midnight WHES energy reset, audit/health
  history, syslog, ACME and encrypted complete backup/restore.
- Fleet inventory, policy and rollout API consumed by the standalone Home
  Assistant add-on.

### Changed

- Replaced the original monolithic runtime with explicit application, service,
  transport, storage, driver and recovery boundaries.
- Moved Home Assistant fleet management to the standalone
  `HAMD-Home-Assistant-Addons` repository.

### Fixed

- Corrected portal restart responses, update progress/error propagation,
  configuration restore validation, API error status, permission-aware actions
  and bounded update storage.

## 1.9.0 - 2026-08-22

Final release of the original architecture. v2 devices are provisioned as
clean seeds and do not depend on v1 configuration compatibility.
