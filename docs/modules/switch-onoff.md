# On/off switch input

## Hardware and configuration

Use `class: switch` and `subclass: onoff` for a local momentary input. Set
`gpio.input.0`. The driver enables the ESP32 pull-up, so wire a dry,
normally-open contact between the GPIO and ground. Never apply external voltage.

## Behaviour and state

The input invokes the locally linked output action defined by the module
configuration. It is intentionally not a separately discovered Home Assistant
entity and is not a remote command target. Its module state and diagnostics are
still available to the portal/API for support purposes.

## Diagnostics

Use diagnostics to confirm input transitions and resource ownership. Repeated
or spontaneous presses indicate contact bounce, long/noisy cabling, missing
ground or an unsuitable external circuit. Add hardware debounce/filtering when
the installation environment requires it.
