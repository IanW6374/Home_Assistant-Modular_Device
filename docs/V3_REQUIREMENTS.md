# IoT-MD v3 requirements baseline

V3 preserves the user-visible capability of stable v2.5 while changing its
implementation boundaries. Each requirement has one primary owner.

| ID | Requirement | Owner |
| --- | --- | --- |
| PLAT-01 | Recover and accept a signed release without a product runtime | Platform |
| PLAT-02 | Enforce secure boot, flash encryption and encrypted secret storage | Platform |
| PLAT-03 | Provide paired platform/runtime trial, confirmation and rollback | Platform |
| PLAT-04 | Expose bounded boot, reset, heap, storage and capability diagnostics | Platform |
| PLAT-05 | Own physical resources and qualified network/USB interfaces | Platform |
| RUN-01 | Validate, version and transactionally migrate configuration | Runtime |
| RUN-02 | Supervise services and modules with bounded health/event history | Runtime |
| RUN-03 | Support declarative resource-aware modular drivers | Runtime |
| RUN-04 | Provide MQTT and optional Home Assistant discovery | Runtime |
| RUN-05 | Provide role-aware HTTPS portal and mTLS Device API v3 | Runtime |
| RUN-06 | Orchestrate certificate enrollment, renewal and trust administration | Runtime |
| RUN-07 | Provide audit, syslog, support and connectivity diagnostics | Runtime |
| REL-01 | Publish one ordinary universal artifact with SBOM and provenance | Host/platform |
| REL-02 | Enforce monotonic release sequence and component compatibility | Platform |
| REL-03 | Import v2 backup data without modifying confirmed v2 state | Host/runtime |
| FLEET-01 | Report bounded inventory, health and release state | Runtime |
| FLEET-02 | Apply signed scoped policy and support canary rollout | External/runtime |
| QUAL-01 | Pass host, HIL, interruption, rollback and soak gates | Host/HIL |
| QUAL-02 | Bind persistent evidence to one release and refuse active-v3 cutover until every required gate passes | Runtime/platform |

## Explicit non-goals for the first alpha

- No attempt to enable USB NCM before the native interface passes packet,
  reconnect, host, TLS and recovery tests.
- No dynamic unsigned driver or plugin loading.
- No browser-heavy single-page application.
- No direct in-place conversion of the v2 filesystem or encrypted namespace.
- No ESP-IDF 6 selection until the chosen MicroPython baseline supports it and
  an independent platform build is qualified.
