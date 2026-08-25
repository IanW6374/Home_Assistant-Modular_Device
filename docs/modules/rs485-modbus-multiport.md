# RS485 Modbus Multiport

Use `class: sensor` and `subclass: RS485-Modbus-Multiport` when one module needs
multiple independent RTU buses. Define each bus under `rs485.ports` with a
unique name and the same UART, pin, framing, DE and timeout fields described in
the [single-port guide](rs485-modbus.md). Each entity selects its bus with
`port`; the default is `ch0`.

Polling, register grouping, decoding, MQTT requests and diagnostics are shared
with the single-port driver. Each configured port must use an available UART
and non-conflicting pins.
