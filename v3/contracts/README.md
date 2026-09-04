# Native/runtime contracts

Contracts are the compatibility boundary between the ESP-IDF platform and the
MicroPython runtime. Every contract has an integer ABI version, fixed limits,
explicit optional fields and fail-closed validation.

The executable contracts currently describe platform capabilities and paired
update state. Alpha 2 also defines the native whole-namespace snapshot calls:

- `storage_open(namespace)` returns an opaque bounded handle;
- `storage_snapshot(handle)` returns one generation and byte payload;
- `storage_commit(handle, expected_generation, payload)` performs a bounded
  compare-and-swap commit; and
- `storage_close(handle)` releases the process-local handle.

Later alpha milestones will add:

- platform events and native job completion;
- opaque credential and certificate handles;
- migration checkpoints;
- network-interface lifecycle;
- resource allocation;
- native update staging, trial and rollback operations; and
- bounded health snapshots.

Schema files document values for host tools and tests. The native module and
MicroPython adapter will use generated/shared constants where practical rather
than separate hand-maintained interpretations.
