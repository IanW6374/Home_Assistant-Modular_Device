# ADR-0001: Native ESP-IDF platform with MicroPython product runtime

- Status: accepted for alpha scaffold
- Date: 2026-09-01

## Context

IoT-MD grew from a MicroPython sensor application into a secure modular device
platform. Boot, recovery, OTA, encrypted storage, USB/network integration and
hardware capability require tighter platform control, while modules and product
services benefit from MicroPython's development speed and accessibility.

## Decision

V3 will be a native ESP-IDF platform which embeds a replaceable MicroPython
runtime. Native code owns durable mechanisms and exposes one bounded versioned
ABI. MicroPython owns product policy, modules, services and presentation.

## Consequences

- Platform recovery does not depend on the product runtime.
- USB NCM or another native interface can be added without changing services.
- The custom platform and its MicroPython integration require independent HIL,
  security and release qualification.
- V2 code is ported by behavior and contract, not moved wholesale.
