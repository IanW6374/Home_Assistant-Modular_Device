# On/off switch input

Use `class: switch` and `subclass: onoff` for a local momentary input. Set
`gpio.input.0` to the GPIO. The driver enables the ESP32 pull-up, so wire the
normally-open contact between that GPIO and ground. The input is used for local
device actions and is not independently published through Home Assistant
discovery.

Use a dry, voltage-free contact. External voltage on an ESP32 GPIO can damage
the device.
