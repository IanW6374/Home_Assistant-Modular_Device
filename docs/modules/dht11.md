# DHT11 temperature and humidity

## Hardware and configuration

Use `class: sensor` and `subclass: dht11`. Configure `gpio.input.0` as the data
pin and add `temperature` and/or `humidity` entities. Each entity needs `class`,
`unit` and an initial `value`. `pollinterval` defaults to 60 seconds; do not poll
the DHT11 faster than its data sheet permits.

Power the sensor at a compatible voltage and fit the data-line pull-up required
by the module board. GPIO numbers are ESP32-S3 numbers. The DHT11 is a
low-accuracy ambient sensor and is unsuitable for safety or process control.

## State and integrations

State is one JSON object on the configured module state topic and through
`GET /api/v2/modules/{uuid}/state`:

```json
{"temperature":21.4,"humidity":48}
```

When the Home Assistant profile is enabled, each configured entity is
discovered as a sensor using its class and unit. The driver is read-only; MQTT
and API commands have no hardware effect.

## Diagnostics

Diagnostics show setup/read failures and the age of the last successful sample.
Repeated failures normally indicate a missing pull-up, an incorrect pin, long
or noisy wiring, or an excessive polling rate. A failed sample retains the last
valid state rather than publishing invented data.
