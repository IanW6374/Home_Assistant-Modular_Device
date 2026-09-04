# Native/runtime contracts

Contracts are the compatibility boundary between the ESP-IDF platform and the
MicroPython runtime. Every contract has an integer ABI version, fixed limits,
explicit optional fields and fail-closed validation.

The executable contracts currently describe platform capabilities, paired
update state, runtime configuration, bounded kernel snapshots and unified
connectivity diagnostics. Alpha 2 defines the native whole-namespace snapshot
calls:

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

Later alpha milestones will add:

- platform events and native job completion;
- opaque credential and certificate handles;
- migration checkpoints;
- network-interface lifecycle;
- native update staging, trial and rollback operations; and
- native platform event and boot-health snapshots.

Schema files document values for host tools and tests. The native module and
MicroPython adapter will use generated/shared constants where practical rather
than separate hand-maintained interpretations.
