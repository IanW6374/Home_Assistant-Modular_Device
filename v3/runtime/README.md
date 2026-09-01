# MicroPython application runtime

The runtime owns product behavior:

- configuration validation, migration and policy;
- service composition, task supervision and health interpretation;
- module discovery, resource requests, drivers, state and commands;
- MQTT, Home Assistant, portal and Device API behavior;
- certificate enrollment policy and renewal orchestration;
- fleet, audit, support and operational diagnostics; and
- transport-neutral request, response and event models.

Runtime code consumes only the versioned platform ABI. It may request a
platform operation but cannot access partitions, raw encrypted storage, native
network handles or key bytes. Services depend on domain contracts; HTTP, MQTT,
display and future USB transports are adapters.

The portal remains server-rendered with bounded enhancement JavaScript. Form
metadata and navigation are declarative so first-boot and maintenance pages
reuse validation, labels and help text.
