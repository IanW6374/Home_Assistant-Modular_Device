# Changelog

## 2.0.12 - 2026-08-25

- Restore Web Portal and Device API request handling when the v2.0.11
  application is bootstrapped on a v2.0.9 core that does not yet provide the
  optional buffered HTTP reader and timeout classifier.
- Retain the persistent-connection performance improvements automatically
  after the matching core has been installed.

## 2.0.11 - 2026-08-25

- Reclaim only the inactive application generation when a universal resumable
  upload would otherwise exceed available storage; the active generation is
  never removed.
- Compact a completed `.hamu` in place after its core component is written,
  adopting the verified inner `.hamd` without temporarily storing both files.
- Release resumable metadata before installation mutates its artifact so an
  interrupted compaction is safely replaced by the next upload attempt.

### Upgrade from 2.0.9 or 2.0.10

- Install `application-2.0.11.hamd` first to update the uploader, restart and
  confirm it, then install `universal-2.0.11.hamu` to update the core.

## 2.0.10 - 2026-08-25

- Reuse normal Web Portal and mTLS API connections for up to 32 requests,
  avoiding a new TLS handshake for every navigation, asset, or API call.
- Buffer encrypted HTTP reads, briefly cache read-only portal status snapshots,
  and allow versioned CSS and JavaScript assets to remain in the browser cache.
- Reuse the API client fingerprint within its TLS connection while checking the
  live registry on every request so scope changes and revocation remain immediate.
- Make the Device restarting page enter readiness checks even when a fast reboot
  occurs between offline probes, and cache-bust every automatic reconnect probe.

## 2.0.9 - 2026-08-25

- Resume interrupted universal `.hamu` uploads from their last committed chunk
  and reclaim only an inactive application generation when staging space is
  otherwise insufficient.
- Report remote syslog delivery failures and recovery in the local Device log,
  with delivery, queue, drop and failure counters in runtime status.
- Remove retired one-shot portal upload routes and extract module presentation
  logic from the runtime composition root.
- Restore linked documentation for every supported module type, correct the
  production N8R8 hardware specification, and record v2.0.8 field qualification.

## 2.0.8 - 2026-08-24

### Changed

- Reordered the remote syslog Transport and Port fields and select port 514
  for UDP or 6514 for TLS when the administrator changes transport, while
  retaining support for a subsequent custom port override.
- Aligned the restart and shutdown controls on the right and emphasized the
  physical-recovery implications of shutdown with a danger action.
- Restart pages now wait until the portal has gone offline, then retry every
  two seconds and return to login only after the restarted portal responds.

### Fixed

- Hide and disable the private-key file control for certificate types that
  require only one or more certificate files.
- Restore shutdown through the hardware deep-sleep capability supplied by the
  matching core firmware release.

### Upgrade order

- The universal `.hamu` release activates core firmware before the application.
- When installing the component files manually, install the `.hamf` first and
  the `.hamd` second so the shutdown capability is available to the portal.

## 2.0.7 - 2026-08-24

### Changed

- Standardized Logging configuration terminology on Device log entries and
  Audit log events, replacing the former system logs and audit events labels.

## 2.0.6 - 2026-08-24

### Changed

- Renamed Maintenance Log viewer to Device log throughout the portal.

## 2.0.5 - 2026-08-24

### Added

- Replaced the Maintenance Factory default tab with Device control, adding
  non-destructive restart and deep-sleep shutdown actions while retaining the
  factory reset workflow in a separate danger section.
- Added audit events for authenticated restart and shutdown requests.

## 2.0.4 - 2026-08-24

### Changed

- Positioned the authenticated user badge before the Sign out button in the
  portal tab banner.

## 2.0.3 - 2026-08-24

### Fixed

- Removed the remaining unsupported `str.capitalize()` calls from
  authenticated portal rendering on MicroPython.
- Extended the MicroPython compatibility gate to reject unsupported
  `capitalize()` and `title()` calls in application bundles.

## 2.0.2 - 2026-08-24

### Added

- Added a dedicated administrator Audit log under Maintenance for portal
  authentication, authorization and mTLS API connection events.
- Added independent remote-syslog forwarding controls for device logs and
  audit events.

### Changed

- Moved routine authenticated portal page requests and API request traces to
  DEBUG-level system logging instead of emitting them as INFO audit messages.

### Fixed

- Restored authenticated portal rendering on MicroPython cores whose compact
  string implementation does not provide `str.isalnum()`.
- Added a MicroPython compatibility check that rejects unsupported
  `str.isalnum()` calls before an application bundle is built.

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
