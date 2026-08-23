# Changelog

All notable user-visible changes are recorded here. This project follows
Semantic Versioning for product release labels.

## [2.0.0-alpha.3] - 2026-08-23

### Fixed

- Made resumable-upload SHA-256 verification use the MicroPython-compatible
  `digest()` API instead of CPython-only `hexdigest()`.

## [2.0.0-alpha.2] - 2026-08-23

### Fixed

- Migrated persisted v1 API-client registries during the v1.9-to-v2 upgrade so
  System configuration pages do not fail after an enrolled client is retained.
- Returned an explicit HTTP error response when a portal route fails instead of
  silently dropping the browser connection.
- Added a signed HAMU format-1 bootstrap envelope for installing v2 on the v1.9
  universal-update loader and retained formats 1 and 2 in v2.
- Started upload-status polling before resumable transfer completion so an
  early server rejection cannot leave a stale upload percentage in the portal.

## [2.0.0-alpha.1] - 2026-08-22

### Added

- Service-oriented runtime and portal internals with explicit driver, event,
  fleet-management and configuration contracts.
- A Home Assistant add-on for single-device management initially, with staged
  rollout, maintenance-window and fleet expansion support built into its data
  model.
- Role-based portal access, selective restore, support bundles, resumable
  uploads, restart-minimised certificate activation and richer universal
  update policy.
- Reproducible-build metadata, SBOM output, parser fuzzing, portal accessibility
  checks and single-device hardware-in-the-loop release qualification.
- Versioned `/api/v2` inventory, structured event, support-bundle and signed
  fleet-policy resources over mandatory mutual TLS.
- Exact-offset, SHA-256-verified resumable application, core and universal
  uploads with independently reported staging and verification progress.
- Independent portal identities and sessions with viewer, operator and
  administrator roles.

## [1.9.0] - 2026-08-22

### Added

- Named time zones with daylight-saving rules and local-time scheduled checks.
- Password-encrypted complete backup and restore, including credentials,
  certificates, trust stores, ACME state, API clients, and module settings.
- Multiple independent CA trust stores and bounded Device API client enrolment.
- Versioned mutual-TLS Device API, API status, audit events, and health counters.
- Configurable portal timeout, log retention, UDP/TLS syslog, and ACME directory.
- Timestamped and resettable persistent health history.
- Daily/weekly automatic release checks and universal `.hamu` upgrades.
- Wi-Fi network selectors with manual hidden-SSID entry in setup and the portal.
- Signed-build source provenance, exact dependency pins, OTA size gates, and a
  complete secure ESP32-S3 CI firmware build.

### Changed

- Portal workflows use one active action, persistent completed stages, bounded
  percentage progress where measurable, and consistent right-aligned actions.
- System NTP is now **Time / Date**; logging configuration is under **System**.
- Backup, certificate, health, logging, and upgrade pages use consolidated
  sections and link to related configuration where appropriate.
- Core and application versions use the same product label; MicroPython is
  displayed separately.
- Portal ports expose their effective defaults instead of a blank value.
- Release checks no longer run merely because the Upgrades page is opened.

### Fixed

- Grove AC-voltage calibration persists and returns to diagnostics.
- Configuration-import conversion and preview-state failures.
- Firmware verification/activation/restart workflow and stale progress status.
- API invalid UUID handling, audit logging, response latency, and TLS startup.
- Portal audit route identity, health-history timestamps/formatting/grouping,
  and update-result layout.
- ESP32 epoch conversion, daylight-saving schedules, and WHES daily-energy
  reset at local midnight.

## Post-1.9

Planned engineering work is maintained in
[`docs/POST_V1_9_RECOMMENDATIONS.md`](docs/POST_V1_9_RECOMMENDATIONS.md).
