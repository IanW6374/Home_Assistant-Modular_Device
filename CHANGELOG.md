# Changelog

All notable user-visible changes are recorded here. This project follows
Semantic Versioning for product release labels.

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
