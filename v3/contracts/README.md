# Native/runtime contracts

Contracts are the compatibility boundary between the ESP-IDF platform and the
MicroPython runtime. Every contract has an integer ABI version, fixed limits,
explicit optional fields and fail-closed validation.

The executable contracts currently describe platform capabilities, paired
update state, runtime configuration, bounded kernel snapshots, unified
connectivity diagnostics, identity metadata, fleet reports, migration plans,
the supported driver catalog and release-bound qualification evidence. Alpha 2
defines the native whole-namespace snapshot calls:

- `storage_open(namespace)` returns an opaque bounded handle;
- `storage_snapshot(handle)` returns one generation and byte payload;
- `storage_commit(handle, expected_generation, payload)` performs a bounded
  compare-and-swap commit; and
- `storage_close(handle)` releases the process-local handle.

Alpha 3 adds the resource boundary:

- `resource_claim(kind, identifier, owner)` returns an opaque exclusive claim;
- `resource_release(handle)` releases one claim;
- `resource_release_owner(owner)` cleans up an application owner; and
- `resource_snapshot()` returns at most the advertised number of primitive
  claim records.

Alpha 4 adds a bounded diagnostic record for DNS, time, TLS, MQTT, CA, syslog
and release-service reachability. Product services exchange bounded request,
response and state values; socket and TLS objects remain inside adapters.

Alpha 5 advances runtime configuration to version 3. Identity records contain
only metadata and opaque certificate/key handles. Fleet reports expose bounded
inventory, release, health, canary and event-cursor values. Migration plans
record preview/staging state and opaque handles without embedding credentials,
keys or protected files. The driver catalog is static and modules may declare
multiple logical resources.

Alpha 6 adds a 15-gate qualification evidence contract. It preserves
`not-run`, `in-progress`, `passed` and `failed` as distinct states, binds the
campaign to one version and monotonic release sequence, and never treats an
unreachable probe as a health or storage observation. The beta profile also
requires sustained observation counts rather than accepting one late sample as
evidence for the complete soak.

Later platform milestones will add:

- platform events and native job completion;
- native-backed credential, certificate and migration handles;
- network-interface lifecycle;
- native update staging, trial and rollback operations; and
- native platform event and boot-health snapshots.

Schema files document values for host tools and tests. The native module and
MicroPython adapter will use generated/shared constants where practical rather
than separate hand-maintained interpretations.
