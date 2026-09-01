# Native/runtime contracts

Contracts are the compatibility boundary between the ESP-IDF platform and the
MicroPython runtime. Every contract has an integer ABI version, fixed limits,
explicit optional fields and fail-closed validation.

The initial executable contract describes platform capabilities. Later alpha
milestones will add:

- platform events and native job completion;
- opaque credential and certificate handles;
- storage transactions and migration checkpoints;
- network-interface lifecycle;
- resource allocation;
- update staging, trial and rollback state; and
- bounded health snapshots.

Schema files document values for host tools and tests. The native module and
MicroPython adapter will use generated/shared constants where practical rather
than separate hand-maintained interpretations.
