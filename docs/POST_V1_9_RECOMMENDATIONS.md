# Post-v1.9 engineering recommendations

These items were intentionally deferred until after the v1.9 release boundary.
The v2 alpha implements the foundations below. Remaining physical-fixture and
external-signing work is explicitly identified rather than hidden as a device
firmware defect.

## Runtime and portal decomposition

- Split `HA-Device.py` into network lifecycle, MQTT/discovery, module runtime,
  portal adapters, and update orchestration services with narrow interfaces.
- Split `web_portal.py` into route registration, page renderers, form parsing,
  backup/certificate workflows, and update workflows.
- Move browser scripts into separately testable static assets while retaining
  the current ESP32 memory and request-count limits.
- Perform the work incrementally with characterization tests and no route,
  configuration, MQTT topic, or upgrade-format changes in the same commits.

## Hardware-in-the-loop release qualification

- Add an ESP32-S3 test rack covering interrupted HAMD/HAMF/HAMU uploads,
  power loss during staging, rollback, recovery entry, and trial confirmation.
- Exercise mTLS client enrolment/revocation, ACME renewal, syslog TLS, backup
  round trips, hidden Wi-Fi networks, DST transitions, and local midnight.
- Record partition use, minimum heap, scan latency, API latency, and flash-write
  counts as release baselines with regression thresholds.

The v2 production core now enforces its partition baseline during every secure
build: 80% produces a warning and 85% fails. Unused Bluetooth/NimBLE, PPP and
SPI-Ethernet stacks are excluded and checked against both generated sdkconfig
and the final linker map. Heap and on-device latency baselines still require the
physical test fixture.

## Reproducibility and supply chain

- Produce an SBOM for Python, MicroPython, ESP-IDF, and native components.
- Record toolchain/container digests in addition to source commit pins and
  compare independently rebuilt application-image hashes where deterministic.
- Sign published release indexes and artifacts with an externally auditable
  release service or hardware-backed offline signing workflow.
- Add a documented update-signing and Secure Boot key-rotation/recovery plan.

## Fleet operations

- Add staged rollout cohorts, maintenance windows, failure-rate stops, and
  fleet-level rollback controls before enabling automatic activation broadly.
- Export health/audit events to a central observability system with retention,
  privacy, rate-limit, and clock-quality policies.
- Evaluate an event-driven/native Wi-Fi scanning API so even the background
  scan itself does not briefly occupy the MicroPython event loop.

## Quality and compatibility

- Add browser accessibility and responsive-layout automation at supported
  desktop/mobile widths.
- Fuzz bundle, HTTP, JSON, certificate, backup, and Modbus parsers within their
  device memory limits.
- Establish a documented compatibility policy before any post-1.9 schema,
  recovery API, core API, or update-format change.

## v2 alpha implementation status

- The runtime uses a sealed application context, ordered lifecycle, supervised
  named tasks, resource-preflighted drivers, unified update coordinator and
  structured event sinks. Portal dependencies, routes and view models are
  separate from HTTP rendering; the retained entry points are composition
  adapters rather than sources of new domain behavior.
- The one-device HIL recorder is implemented. Power-interruption, ACME, syslog,
  DST and local-midnight cases still require execution against the physical
  fixture before promotion beyond alpha.
- CycloneDX SBOM and SLSA-compatible provenance generators are implemented.
  External transparency logging or hardware-backed signing remains a release
  infrastructure deployment choice, not something safely emulated in source.
- Ordered rollout cohorts, maintenance windows, signed policies, bounded event
  retention and automatic failure stops are implemented in the Home Assistant
  add-on. SQLite transactions and durable idempotent retry jobs replace the
  alpha JSON/in-memory prototype.
- Deterministic parser fuzzing and structural accessibility automation run in
  CI. Native/event-driven Wi-Fi scanning remains dependent on the MicroPython
  network API and is not required for alpha correctness.
- v2 is deliberately clean-seed while there is one test device. The v1 API and
  bootstrap HAMU format are not shipped; compatibility begins with the v2
  contracts and must be frozen before v2 stable.
