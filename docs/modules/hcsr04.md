# HCSR04 ultrasonic distance

## Hardware and configuration

Use `class: sensor` and `subclass: hcsr04`. Configure `gpio.input.trig` and
`gpio.input.echo`; add one `distance` entity, normally with `cm` as its unit.
`pollinterval` defaults to 60 seconds and the echo timeout is 10,000 µs.

The common HC-SR04 echo output is 5 V. Use a divider or level shifter so the
ESP32-S3 GPIO never receives more than 3.3 V. Aim the transducer away from
near-field obstructions and allow for the sensor's minimum range and beam width.

## State and integrations

The state/API payload is `{"distance":123.4}`. The configured MQTT state topic
and `GET /api/v2/modules/{uuid}/state` carry the same transport-neutral value.
Home Assistant discovery creates one distance sensor when enabled. This is a
read-only module.

## Diagnostics

An echo timeout or unchanged implausible value normally points to incorrect
trigger/echo pins, missing common ground, 5 V connected directly to the ESP32,
or a target outside the usable range. Diagnostics record read/setup failures and
last-update age.
