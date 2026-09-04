# Changelog

## 3.0.0-alpha.3 - 2026-09-04

- Advance the native platform boundary to ABI 3 with owner-scoped, bounded
  resource claims for ADC, GPIO, I2C, SPI and UART identities.
- Add an exact, versioned runtime configuration contract and a non-mutating
  migration preview from the initial draft configuration.
- Add the greenfield application kernel, dependency-aware service registry and
  cooperative supervisor with isolated degradation, restart and cleanup.
- Port a small reference sensor through the new driver/resource contracts and
  cover restart, invalid configuration, resource conflict and transient failure.
- Add bounded health, event and support snapshots with executable JSON schemas;
  configuration settings and secret material are not included.
- Retain the v2.5 compatibility product runtime and keep hardware-only Alpha 1
  and Alpha 2 recovery gates explicitly open.

## 3.0.0-alpha.2 - 2026-09-04

- Advance the native platform boundary to ABI 2 with bounded opaque encrypted-
  NVS namespace handles and alternating, CRC-protected snapshot generations.
- Add the runtime transactional-storage adapter and the first executable paired
  platform/runtime state machine covering staging, trial, confirmation,
  mismatch detection and restoration of the previous confirmed pair.
- Add schemas and interruption tests proving each Alpha 2 state transition
  recovers to either the complete old generation or complete new generation.
- Return from update-finalisation requests immediately and run verification as
  an asynchronous task, allowing the portal to display live firmware and
  application byte progress instead of remaining at zero percent.
- Install the Management Suite release-signing key through its own validated,
  power-safe protected-file transaction instead of incorrectly routing it
  through the X.509 certificate path validator.
- Keep native paired trial selection and rollback capability reported as
  unavailable until partition-control and power-cut HIL qualification pass.

## 3.0.0-alpha.1 - 2026-09-01

- Add the first versioned native `_iotmd_platform_v3` capability ABI and a
  fail-closed MicroPython adapter backed by an executable JSON contract.
- Report the real platform security, PSRAM, OTA partition and interface gates
  without claiming USB NCM availability.
- Retain the stable v2.5 product behavior as an explicitly temporary
  compatibility payload so the new native/runtime boundary can be qualified
  independently before application services are ported.

## 2.5.0 - 2026-09-01

- Promote the tested 2.5 beta series to stable with transport-neutral Device
  API contracts, smaller API projections and centrally resolved feature flags.
- Add hardware resource management, explicit USB/NCM capability diagnostics
  and safe ESP32-S3 gating while retaining Wi-Fi as the production transport.
- Improve runtime reliability, boot-health reporting, certificate and logging
  navigation, portal-user administration and consistent upgrade terminology.
- Finalise the Status, Device, Module, User, Maintenance navigation order with
  alphabetised destinations, click-to-expand Maintenance categories and
  origin-preserving avatar-menu password changes.

## 2.5.0-beta.5 - 2026-09-01

- Restore the requested Status, Device, Module, User, Maintenance top-level
  order while keeping the destinations within each dropdown alphabetical.
- Make the Maintenance Certificates and Logging categories click-to-expand,
  keep unrelated categories collapsed, and retain the active category on its
  destination pages.
- Return successful avatar-menu password changes to the originating portal
  page and give portal-user cards a bounded width with clearly separated user
  actions.

## 2.5.0-beta.4 - 2026-09-01

- Standardise the portal navigation around **Device**, **Maintenance**,
  **Module**, **Status** and **User**, alphabetise destinations and render
  certificate and logging destinations as always-visible labelled groups in
  the Maintenance menu.
- Rename Messaging to **MQTT**, Device control to **Power & reset**, and use
  **upgrade** consistently for device software installation while retaining
  compatible internal `update` routes and state keys.
- Move password changes into an avatar-menu dialog, split existing and new
  portal users, and allow administrator usernames and other portal identities
  to be renamed without invalidating their current sessions.
- Restore Health History timestamps and expose current device state, boot
  stage, active network transport, hardware allocations, USB NCM availability
  and effective runtime features alongside the persistent health counters.

## 2.5.0-beta.3 - 2026-09-01

- Replace the flat certificate links in Maintenance with a grouped
  **Certificates** submenu containing enrollment, CA/signing trust, API client
  trust and device-certificate destinations.
- Keep the certificate destinations visible whenever Maintenance is open,
  mark the active destination and increment the portal asset version so
  browsers fetch the corrected navigation CSS and JavaScript.

## 2.5.0-beta.2 - 2026-09-01

- Freeze the TLS-session compatibility seam required by the recovery-layer
  release client, allowing a firmware-first universal trial to start while the
  previous application generation is still active.
- Enforce the complete project-local import closure of every frozen recovery
  module at build/test time, preventing another core from depending on files
  available only in its matching application bundle.

## 2.5.0-beta.1 - 2026-09-01

- Introduce transport-neutral Device API request/response contracts and retain
  HTTPS/mTLS as an adapter, allowing the same API router to serve any qualified
  IP interface without duplicating domain behavior.
- Add smaller `/api/v2/device`, `/interfaces`, `/hardware`, `/services`, and
  `/configuration` projections while retaining the combined inventory endpoint
  for backward compatibility.
- Add central signed feature flags resolved against the release channel,
  firmware build and detected runtime capabilities; expose both enabled state
  and the reason a requested feature is unavailable.
- Add the experimental USB NCM transport contract, lifecycle and capability
  gating. The current ESP32-S3 core reports it unavailable because MicroPython
  1.29's generic driver is not yet integrated with the ESP32 network/TinyUSB
  port; Wi-Fi remains the required interface.
- Separate USB device hardware, NCM hardware, runtime symbol and validated NCM
  availability diagnostics so `network.USBD_NCM` alone cannot enable the
  production transport.
- Add an opaque TLS-session handle accepted by outbound clients without claiming
  resumption support on MicroPython 1.29, which exposes no stable session API.
- Extend hardware preflight into an owner-scoped logical resource manager with
  provider injection and shared-instance caching; migrate MAX31865 SPI and
  chip-select construction to the injected resource path.
- Show a healthy running Device State tile with the same green treatment as
  other healthy services and keep certificate destinations persistently visible
  in the open Maintenance menu.

## 2.4.0-beta.3 - 2026-08-31

- Expose all four certificate-management destinations directly in the
  Maintenance menu and remove the redundant certificate-page tab bar.
- Expand managed-task diagnostics with lifecycle state, criticality, start and
  failure counts, last error, and successful heartbeat timing.
- Record current free and allocated heap alongside the minimum free heap since
  boot, without making point-in-time observations trigger flash checkpoints.
- Route portal background operations through the central task supervisor so
  their failures participate in the same runtime-health model.

## 2.4.0-beta.2 - 2026-08-31

- Load the activation-heap policy through the signed application settings
  boundary, fixing the beta.1 startup `NameError` observed on hardware.
- Guard the compact application entry against an older recovery core after a
  paired firmware rollback, restoring the confirmed application without
  importing modules available only in the newer frozen core.

## 2.4.0-beta.1 - 2026-08-31

- Add a staged boot supervisor record covering platform, persistent state,
  update reconciliation, filesystem, configuration, certificates, hardware,
  network, portal, essential services, activation health and running state.
- Retain the compact boot record across resets in CRC-protected RTC no-init
  memory provided by the native IoT-MD platform module, with an atomic flash
  fallback and no secret material.
- Detect runtime capabilities rather than inferring them from the MicroPython
  version, including PSRAM heap, OTA partitions, watchdog and reset-persistent
  memory support.
- Refuse trial confirmation when required PSRAM, activation heap, local portal,
  network or a configured watchdog is unavailable; classify NTP, Device API,
  MQTT and other external-service failures as degraded operation.
- Expose the unified device state, boot stage, boot record and capability
  matrix through portal status, Device API inventory and support bundles.
- Preserve the proven MicroPython 1.29.0 and ESP-IDF 5.5.1 toolchain while the
  boot architecture is qualified independently of a future IDF major upgrade.

## 2.3.13 - 2026-08-31

- Place the four certificate-management pages beneath a single Maintenance >
  Certificates entry with a persistent certificate submenu and hierarchical
  breadcrumbs.
- Show the manual portal or Device API certificate-and-key upload controls
  directly when Manual certificate package is selected, retaining the
  Certificate enrollment page after validation.

## 2.3.12 - 2026-08-31

- Restore the ESP32-S3 PSRAM-backed MicroPython heap in the 1.29 firmware by
  combining the S3 SPIRAM base settings with the octal-mode variant.
- Reject production core builds when PSRAM, boot initialisation, malloc
  integration, or octal mode is absent, preventing internal-RAM-only firmware
  from being packaged again.

## 2.3.11 - 2026-08-31

- Store large renderer-local HTML and JavaScript constants as bounded 2 KiB
  chunks in compact application bytecode, deferring their assembly until the
  relevant page is requested.
- Eliminate the hardware-observed 8,850-byte contiguous allocation during
  `portal_live_views` import while preserving byte-for-byte renderer output.
- Use core-firmware-first activation for the v2.2.9 to v2.3.11 universal
  transition so MicroPython 1.29 and the compact v2.3 application start as one
  paired, rollback-protected trial.

## 2.3.10 - 2026-08-31

- Extract the remaining access-control and update-upload dispatchers from the
  portal transport after the v2.3.9 hardware trial showed its reduced module
  still requested the same 8,850-byte aggregate import allocation.
- Preserve login/session mutations across the access-route boundary and share
  upload progress through an explicit request-state record.
- Reduce the compiled portal transport from 13,286 to 8,550 bytes and tighten
  its build-time growth ceiling to 10,000 bytes.

## 2.3.9 - 2026-08-31

- Compile the settings and live portal route dispatchers as independent
  MicroPython modules, eliminating the aggregate 8,850-byte allocation that
  caused the v2.3.8 A/B trial to roll back despite ample total free heap.
- Add compact-bytecode size gates for the portal transport and extracted route
  modules so future portal growth cannot silently restore the trial-boot fault.

## 2.3.8 - 2026-08-31

- Load the split portal transport through a release-specific application
  module identity during A/B trial startup, preventing the active v2.2.9
  generation from satisfying the import with its 8,960-byte handler.
- Compile the canonical portal implementation into that new module name while
  retaining the existing development and test import surface.

## 2.3.7 - 2026-08-30

- Split portal access control, settings, update upload and live routes into
  bounded MicroPython coroutines, reducing the largest portal bytecode
  allocation from 8,687 bytes to 2,471 bytes during trial startup.
- Add architecture ceilings for each portal request-handler boundary so the
  hardware-observed contiguous-allocation failure cannot silently return.

## 2.3.6 - 2026-08-30

- Load the remaining large web-portal bytecode module immediately after a
  startup garbage collection, before smaller imports fragment the heap.
- Add an import-order regression gate for the 17 KiB contiguous allocation
  failure observed during the v2.3.5 hardware trial.

## 2.3.5 - 2026-08-30

- Replace the 126 KiB source application entry with a compact,
  recovery-compatible bootstrap and package the full runtime as precompiled
  MicroPython bytecode.
- Preserve the existing `iotmd.py` activation contract so devices running an
  earlier recovery core can install the application safely.
- Add entry-size and bundle-compaction regression gates to prevent the
  trial-boot source-compilation memory failure from returning.

## 2.3.4 - 2026-08-30

- Reduce normal startup heap pressure by loading certificate-administration
  actions, transport and views only when their portal routes are used.
- Compile the application entry and release its source buffer before execution,
  avoiding a second large live allocation while imports initialize.
- Record free and allocated heap before application load and immediately before
  execution when startup fails, preserving actionable diagnostics in update
  history and on USB serial.
- Add architecture and recovery regression coverage for the lazy certificate
  boundary and loader heap diagnostics.

## 2.3.3 - 2026-08-30

- Reconcile orphaned universal-update transactions after a paired component
  rollback, allowing a remote portal upload to retry without USB intervention
  while preserving legitimate staged and trial updates.
- Preserve the underlying trial-application startup exception in update
  history and print its traceback to USB before performing a paired rollback.

## 2.3.2 - 2026-08-30

- Correct the automatic-upgrade server default to
  `https://iot-upgrade.home.arpa:8443`.

## 2.3.1 - 2026-08-30

- Make the automatic-upgrade release server visible and editable under
  Maintenance > Upgrades, defaulting to
  `https://iotmd-update.home.arpa:8443` and deriving the selected Stable or
  Beta catalog path automatically.
- Require an HTTPS origin with a valid hostname and optional port before a
  release-server change is stored or used.

## 2.3.0 - 2026-08-29

- Accept Management Suite format-3 Stable/Beta release catalogs signed by the
  existing fleet-policy identity, while continuing to verify every downloaded
  application or core bundle with the immutable offline update key.
- Add **Management Suite verification key** import under Maintenance >
  Certificates and retain that shared fleet/catalog trust identity through update, encrypted
  backup/restore and factory reset workflows.
- Preserve format-2 offline-signed release catalogs for direct/static release
  publication.
- Use `iot-md-001` and `iot-md-001.local` as the first-boot device-name and
  mDNS defaults, and align device identity examples without changing the WHES
  module name or identifiers.
- Show remote syslog health alongside Wi-Fi, MQTT and Device API state on the
  overview page.
- Split certificate enrollment, outbound CA/signing trust, Device API client
  trust and device identities into focused Maintenance pages. Show and change
  the active enrollment method, and remove obsolete trust anchors explicitly.
- Standardise **IoT CA enrollment authorization (`.iotenroll`)** and the other
  certificate-method names across first boot, maintenance and IoT CA.
- Include every certificate enrollment, trust and portal module in application
  update bundles, with a regression check against incomplete releases.
- Update the reproducible firmware baseline to MicroPython 1.29.0 while
  retaining the supported ESP-IDF 5.5.1 toolchain.

## 2.2.9 - 2026-08-28

- Standardise the human-facing product acronym as **IoT-MD** across the web
  portal, setup and recovery pages, access-point names, device display,
  Home Assistant metadata, syslog application labels and documentation while
  preserving compatibility-sensitive protocol and update identifiers.
- Keep the daily and weekly automatic-upgrade schedule fields the same width
  as the adjacent release-channel and schedule controls.

## 2.2.8 - 2026-08-28

- Keep the certificate-enrollment **Check status now** button visually stable
  during automatic polling instead of repeatedly applying the disabled style.
- Prevent overlapping automatic and manual enrollment-status requests with an
  internal in-flight guard that does not alter the control’s appearance.

## 2.2.7 - 2026-08-28

- Show only the schedule fields relevant to disabled, daily or weekly automatic
  upgrade checks, and give selects and other form controls a consistent height.
- Combine scanned and manually entered Wi-Fi network names into one editable
  SSID control in both first-boot setup and System > Network.
- Preserve non-secret setup values after a failed Wi-Fi join, clear all
  password fields, and reset the ESP station interface before a retry to avoid
  stale `Wifi Internal State Error` failures.
- Embed the setup-complete page styling before reboot and centre its login
  action, eliminating the remaining Safari render race during first boot.

## 2.2.6 - 2026-08-28

- Close and await setup, recovery and upgrade HTTP responses before restarting
  or continuing background verification, so Safari renders styled transition
  pages immediately instead of waiting for the browser to stop the request.
- Use the same MicroPython-safe stream shutdown for the Device API, outbound
  release and ACME clients, ACME challenge handling and TLS syslog retries.
- Make the factory-reset setup address clickable and add a dedicated
  **Open device setup** button for reconnecting to `http://192.168.4.1`.

## 2.2.5 - 2026-08-27

- Restore **IoT CA enrollment file (`.iotenroll`)** as a first-class setup
  wizard choice instead of hiding it beneath automatic provisioning.
- Standardise certificate method names across IoT-MD and IoT CA.
- Automatically rotate IoT CA public portal, private Device API and renewal
  identities as one authenticated set, and regenerate self-signed identities
  after two-thirds of their lifetime.
- Make **Manual certificate package** the only non-renewing method and warn in
  both the Certificates portal page and Device log.

## 2.2.4 - 2026-08-27

- Validate all portal and recovery password pairs together, marking both
  fields in every mismatched or duplicated pair without retaining stale
  browser validation errors.
- Confirm the home Wi-Fi station connection before presenting the network
  handover page and retain the setup access point long enough to load its UI.
- Keep automatic IoT CA enrollment on a styled progress page that polls the
  device, tolerates temporary connection loss and redirects only after the
  enrollment reaches a terminal state.

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

- Rebrand the product as IoT Modular Device (IoT-MD), including the runtime,
  firmware board, native module, repository references and signed update
  formats (`.iotapp`, `.iotcore` and `.iotuni`).
- Replace platform-specific MQTT topics with administrator-defined templates,
  QoS, retained-state and command-subscription controls.
- Make Home Assistant discovery an optional integration layered over the same
  MQTT connection and combine both settings under **Messaging**.
- Publish a complete API contract, MQTT and Home Assistant integration guides,
  detailed per-module references and the WHES calculation assumptions.
- Define the companion IoT-MD Management Suite for fleet and secure release
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
  containers and the new IoT-MD application, core and universal formats.
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

IoT-MD v2 is the first production release of the clean-seed ESP32-S3 platform.

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
