# On/off light

Use `class: light` and `subclass: onoff` for a binary GPIO output exposed as a
Home Assistant light. Set `gpio.output.0` to the output pin and
`gpio.activeHigh` to `true` for active-high hardware or `false` for an inverted
relay/driver. The sole entity holds `state` (`ON` or `OFF`). Commands arrive on
the module `/set` MQTT topic as `{"state":"ON"}`.

The output pin must drive a suitable transistor, relay or logic input; it must
not directly supply a mains or high-current load. See the common
[module configuration rules](README.md).
