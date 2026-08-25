# On/off light

## Hardware and configuration

Use `class: light` and `subclass: onoff`. Set `gpio.output.0` and
`gpio.activeHigh`; use `false` for an inverted relay/driver. The sole entity has
`state` (`ON` or `OFF`). The GPIO must drive a suitable isolated relay,
transistor or logic input and must never directly supply a mains/high-current
load.

## State and commands

State is `{"state":"ON"}`. Send the same object to the configured MQTT command
topic or `POST /api/v2/modules/{uuid}/commands`. The API returns an operation
record; MQTT publishes the resulting state. Invalid state values are rejected.

Home Assistant discovery creates a light entity only when its profile is
enabled. Generic MQTT and API control remain available without Home Assistant.

## Diagnostics and safe startup

Diagnostics identify the output pin, driver health and last command. Confirm
`activeHigh` with the load safely disconnected: an incorrect polarity can
energize an active-low relay during initialization.
