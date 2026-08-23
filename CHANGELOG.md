# Changelog

All notable user-visible changes are recorded here. This project follows
Semantic Versioning for product release labels.

## [2.0.0-alpha.8] - 2026-08-23

### Changed

- Split portal HTTP helpers, live views, settings views and presenters into
  bounded modules while retaining the existing portal contract.
- Split the first-boot wizard into HTTP control, provisioning workflow and
  pure view modules.
- Split certificate codecs, credential validation, application-slot storage
  and Modbus codecs from their lifecycle and transport owners.
- Moved Home Assistant discovery and availability publishing behind an
  explicit application service.
- Removed clean-seed compatibility aliases and legacy Home Assistant identity
  cleanup that are not required by v2 devices.
- Added enforceable dependency, source-size and retired-compatibility
  architecture gates to CI.

### Fixed

- Preserved all extracted runtime and frozen-core dependencies in application
  and firmware build manifests.
- Removed the recovery/update import cycle by sourcing installed API versions
  directly from the frozen security contract.

## [2.0.0-alpha.7] - 2026-08-23

### Fixed

- Corrected A/B application-update capacity accounting so the uploaded bundle
  reserves one copy and activation reclaims the inactive slot before checking
  space for its replacement.

## [2.0.0-alpha.6] - 2026-08-23

### Added

- Added a persistent portal-banner action for activating configuration changes
  from multiple tabs with one controlled restart.
- Added estimated encrypted-backup validation progress with a confirmed
  completion state.

### Fixed

- Corrected first-boot Wi-Fi scan heading and button proportions.
- Removed a CPython-only string-title call that prevented the User page from
  rendering under MicroPython.
- Allowed restart responses additional time to cross TLS before resetting and
  classified reset/aborted sockets as normal client disconnects.
- Avoided arming a Wi-Fi rollback trial for unrelated settings changes.

## [2.0.0-alpha.5] - 2026-08-23

### Changed

- Reduced immutable-core flash pressure by removing unused Bluetooth/NimBLE,
  PPP and SPI-Ethernet support and selecting size-oriented compilation.
- Tightened production OTA occupancy gates to warn at 80% and fail at 85%,
  with generated-configuration and linker-map checks preventing excluded
  native stacks from returning.
- Replaced implicit runtime wiring with an explicit application context,
  supervised named tasks, ordered lifecycle states, and sealed service
  composition.
- Added deterministic GPIO, UART, SPI and ADC resource preflight and live
  driver lifecycle conformance checks before module startup.
- Routed application, core and universal resumable uploads through one update
  coordinator with named receiver contracts.
- Split portal route policy, dependency contracts and view models from the
  embedded HTTP renderer.
- Replaced fleet JSON state and in-memory work with transactional SQLite state,
  durable idempotent jobs, retry backoff, and separate repository, policy and
  device-client services.
- Made v2 a clean-seed platform: the Device API is exposed only under
  `/api/v2`, and HAMU format 2 is the sole universal-update format.

### Added

- CI architecture dependency enforcement and MicroPython compatibility checks,
  including detection of CPython-only SHA-256 `hexdigest()` use.
- Structured event sinks bridging lifecycle/task events into the existing
  bounded console, portal-log and remote-syslog pipeline.

## [2.0.0-alpha.3] - 2026-08-23

### Fixed

- Made resumable-upload SHA-256 verification use the MicroPython-compatible
  `digest()` API instead of CPython-only `hexdigest()`.
- Made USB application recovery watchdog-safe and able to stage a transferred
  bundle in place without requiring storage for a second full copy.

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
