# Changelog

## 2.2.3 - 2026-08-27

- Keep setup password validation on the wizard page, identify each invalid
  field in red and explain duplicate or mismatched credentials inline.
- Replace the combined certificate page with a choice-first workflow that
  reveals only the selected self-signed, IoT CA, private ACME or manual route.
- Make the IoT CA provisioning port configurable and treat blank IoT CA and
  ACME endpoint fields as the documented `iot-ca.home.arpa` defaults.

## 2.2.2 - 2026-08-27

- Restore the factory-reset first-boot access point by removing an application-
  layer logging dependency from the certificate enrollment module frozen into
  the core.
- Retain certificate enrollment failure diagnostics through the normal Device
  log when the application is mounted and the USB console during first boot.
- Add a regression test that imports the frozen enrollment path with the
  application package deliberately unavailable.

## 2.2.1 - 2026-08-26

- Replace file-backed combined universal staging with a signed sequential
  transport: validate the outer `.iotuni` manifest, then upload and verify its
  signed core and application components one at a time before paired activation.
- Reduce the measured v2.2.0 filesystem peak from 1,974,272 bytes to 1,556,480
  bytes on the device's 4096-byte FAT allocation units.
- Adopt completed resumable application bundles in place instead of creating a
  second full temporary copy.
- Include filesystem allocation rounding and metadata work blocks in update
  preflight checks, and translate raw error 28 into a named storage failure.
- Persist the universal component plan so a browser refresh or interrupted
  component upload resumes without weakening signed size, digest, version or
  release-sequence binding.
- Record the original universal rejection detail, including final state-write
  failures, in update history.
- Add one-step IoT CA certificate provisioning from an explicitly enabled CA
  enrollment window while retaining the one-time authorization-file fallback.
- Correct certificate filename wrapping throughout first boot, and display
  enrollment failures in a red status box with actionable DNS error text.

## 2.2.0 - 2026-08-26

- Add a host-bound IoT CA enrollment workflow to first boot while retaining
  explicit public-certificate, local ACME, manual-certificate and self-signed
  choices for the administrator.
- Generate separate P-256 portal, private Device API and renewal keys on the
  device, submitting only signed CSRs to IoT CA over pinned HTTPS.
- Validate enrollment expiry, authorized hostnames, CSR usages and returned
  identities before activating all certificate and state files atomically.
- Keep Cloudflare credentials and all device private keys on their respective
  systems; neither is included in the enrollment response or persistent token
  state.

## 2.1.3 - 2026-08-26

- Compile importable application modules to compact MicroPython bytecode so a
  universal update remains within the device's safe LittleFS staging budget.
- Reject oversized universal artifacts during the release build instead of
  allowing a device upgrade to fail later with raw error 28 (`ENOSPC`).
- Divide automatic upgrade controls into a manual release check and saved
  automatic-update settings.
- Move signed-in user details and the sign-out action into the avatar menu.

## 2.1.2 - 2026-08-26

- Separate the public portal and private Device API/fleet server identities so
  public portal renewal cannot alter private service trust.
- Extend first-boot provisioning for IoT CA public-portal packages containing
  public portal files, private API files and private trust anchors.
- Preserve separate `.local` mDNS and public portal DNS names for correct TLS
  validation and restart reconnection.
- Include both server identities in complete encrypted backup and validate each
  certificate/key pair before restore.
- Migrate an existing 2.1.1 portal identity once to the independent API path so
  the test device remains manageable until its private identity is installed.
- Standardise portal status presentation with semantic information, success,
  warning and failure boxes, including live upgrade progress and state tiles.

## 2.1.1 - 2026-08-25

- Keep Home Assistant discovery publishing inside the Home Assistant section
  of **Messaging** and clarify the discovery integration label.
- Replace the compact `IM` portal mark with a stacked, accessible `IoT` / `MD`
  mark in both the application and recovery portal shells.
- Compact universal application tails with block-by-block LittleFS reclamation
  so copy-on-write storage does not fail with raw error 28 (`ENOSPC`).
- Correct the documented v2.0 transition to use the v2.0.15 application/core
  components, the v2.0.16 core bridge, then the v2.1 components in order.

## 2.1.0 - 2026-08-25

- Rebrand the product as IoT Modular Device (IoTMD), including the runtime,
  firmware board, native module, repository references and signed update
  formats (`.iotapp`, `.iotcore` and `.iotuni`).
- Replace platform-specific MQTT topics with administrator-defined templates,
  QoS, retained-state and command-subscription controls.
- Make Home Assistant discovery an optional integration layered over the same
  MQTT connection and combine both settings under **Messaging**.
- Publish a complete API contract, MQTT and Home Assistant integration guides,
  detailed per-module references and the WHES calculation assumptions.
- Define the companion IoTMD Management Suite for fleet and secure release
  management while retaining the generic IoT Certificate Authority and IoT
  Syslog Server as independent add-ons.
- Persist upgrade upload, verification, staging, download and activation
  failures in the Device log and structured health/update history with the
  original failure detail.

### Required transition from v2.0

- Install the v2.0.15 application and core components separately, followed by
  the v2.0.16 core bridge and then the v2.1 application and core components.
- Do not use a universal container while crossing the v2.0/v2.1 boundary.

## 2.0.14 - 2026-08-25

- Add a one-time transition core that accepts both the established v2 update
  containers and the new IoTMD application, core and universal formats.
- Allow the normal and recovery upload interfaces to select either generation
  so a deployed v2.0.13 device can cross the v2.1 format boundary safely.

## 2.0.13 - 2026-08-25

- Replace unsupported frozen `bytearray` slice deletion with MicroPython-safe
  buffer slicing so portal and API requests parse correctly on the device.
- Version the optional buffered-reader capability and bypass implementations
  that do not advertise the corrected contract during application-first upgrades.
- Extend the MicroPython compatibility gate to reject slice deletion in future
  application or frozen-core changes.

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
- Compact a completed `.iotuni` in place after its core component is written,
  adopting the verified inner `.iotapp` without temporarily storing both files.
- Release resumable metadata before installation mutates its artifact so an
  interrupted compaction is safely replaced by the next upload attempt.

### Upgrade from 2.0.9 or 2.0.10

- Install `application-2.0.11.iotapp` first to update the uploader, restart and
  confirm it, then install `universal-2.0.11.iotuni` to update the core.

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

- Resume interrupted universal `.iotuni` uploads from their last committed chunk
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

- The universal `.iotuni` release activates core firmware before the application.
- When installing the component files manually, install the `.iotcore` first and
  the `.iotapp` second so the shutdown capability is available to the portal.

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

- Stream universal `.iotuni` upgrades directly into the transactional installers
  instead of caching the complete container on constrained device storage.
- Reclaim superseded or unfinishable resumable uploads automatically and reject
  uploads that cannot fit before they consume the remaining filesystem space.

## 2.0.0 - 2026-08-24

IoTMD v2 is the first production release of the clean-seed ESP32-S3 platform.

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
  `IoTMD-Home-Assistant-Addons` repository.

### Fixed

- Corrected portal restart responses, update progress/error propagation,
  configuration restore validation, API error status, permission-aware actions
  and bounded update storage.

## 1.9.0 - 2026-08-22

Final release of the original architecture. v2 devices are provisioned as
clean seeds and do not depend on v1 configuration compatibility.
