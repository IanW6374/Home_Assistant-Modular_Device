# MicroPython application runtime

The runtime owns product behavior:

- configuration validation, migration and policy;
- service composition, task supervision and health interpretation;
- module discovery, resource requests, drivers, state and commands;
- MQTT, Home Assistant, portal and Device API behavior;
- certificate enrollment policy and renewal orchestration;
- fleet, audit, support and operational diagnostics; and
- transport-neutral request, response and event models.

Alpha 6 adds a persistent operational qualification service and the
compatibility/shadow/active cutover coordinator. Active ownership is refused
unless native paired trial and rollback capabilities are available and all 15
qualification gates contain passing observed evidence. A v3 boot or health
failure requests recovery and returns to compatibility mode. Alpha 5's
declarative identity and fleet services, opaque certificate and
migration handles, signed policy/canary reporting, previewed v2 backup
migration and the complete v2.5 driver catalog over multi-resource claims
remain in place.
Alpha 4's bounded Wi-Fi/MQTT/portal/mTLS API adapters, shared portal metadata
and unified connectivity diagnostics remain transport adapters around those
domains. Alpha 3's service registry, resource adapter, reference sensor and
bounded kernel snapshots remain the composition base. Alpha 2's fail-closed
transactional-storage and paired-release adapters remain in place. The paired
coordinator may describe and reconcile a pair, but cannot select partitions or
claim native rollback; those mechanisms remain platform-owned and
capability-gated off.

Runtime code consumes only the versioned platform ABI. It may request a
platform operation but cannot access partitions, raw encrypted storage, native
network handles or key bytes. Services depend on domain contracts; HTTP, MQTT,
display and future USB transports are adapters.

The portal remains server-rendered with bounded enhancement JavaScript. Form
metadata and navigation are declarative so first-boot and maintenance pages
reuse validation, labels and help text.
