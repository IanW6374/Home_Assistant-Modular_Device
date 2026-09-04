# IoT-MD v3.0.0-alpha.3 test note

## Purpose

Alpha 3 introduces the first isolated greenfield application kernel and a
native logical-resource ownership boundary. The successful Alpha 2 installation
provides the starting hardware baseline; this release retains its transactional
storage and compatible v2.5 product runtime.

## Included

- Native `_iotmd_platform_v3` ABI 3.
- Up to 16 exclusive owner-scoped claims across ADC, GPIO, I2C, SPI and UART
  identities, exposed only as opaque integer handles.
- Exact runtime configuration version 1 and a non-mutating migration preview
  from the draft version 0 structure.
- A dependency-aware service registry and bounded cooperative supervisor with
  running, degraded, failed and stopped states.
- A reference sensor whose sample provider is injectable for host/HIL testing.
- Bounded kernel health, event and support snapshots that omit configuration
  settings and secret material.
- Host tests for restart, configuration failure, resource conflict, transient
  failure recovery and resource cleanup.

## Deliberately incomplete

- The new kernel is not yet the production entry point; the v2.5 compatibility
  runtime continues to provide the portal, MQTT and Device API.
- ABI 3 currently arbitrates logical exclusive ownership. Physical peripheral
  construction and shared-bus policy require later platform/HIL work.
- Native paired partition selection and rollback remain capability-gated off.
- USB NCM remains capability-gated off.

## Safety and rollback

The release sequence is `2708`. Install only on a recoverable test device.
Returning to an older release sequence can require USB recovery or a later
release with a higher sequence.

## Hardware checks

After installation, confirm the existing portal and configured services still
operate. From USB, inspect the new boundary:

```python
import _iotmd_platform_v3
from v3.runtime.iotmd_next.platform import Platform

platform = Platform()
print(_iotmd_platform_v3.ABI_VERSION)
print(platform.capabilities()['resources'])
handle = _iotmd_platform_v3.resource_claim('adc', 'alpha3:fixture', 'hil-test')
print(_iotmd_platform_v3.resource_snapshot())
_iotmd_platform_v3.resource_release(handle)
```

Expected essentials are ABI 3, `managed` true, `max_claims` 16, the five
advertised resource kinds, and an empty snapshot after release. Repeat a claim
with the same owner to confirm idempotency; a different owner for the same
identity must fail with a busy error. Reboot and confirm the compatibility
portal remains healthy.

The Alpha 3 exit gate additionally requires a physical reference-sensor HIL
fixture, repeated service restarts and injected watchdog/configuration/resource
faults without loss of recovery access.
