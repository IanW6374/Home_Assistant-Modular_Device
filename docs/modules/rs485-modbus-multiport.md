# RS485 Modbus Multiport

## Configuration

Use `class: sensor` and `subclass: RS485-Modbus-Multiport` when one module needs
multiple independent RTU buses. Define each bus under `rs485.ports` with a
unique name and the same UART, pin, framing, DE and timeout fields described in
the [single-port guide](rs485-modbus.md). Each entity selects its bus with
`port`; the default is `ch0`.

Polling, register grouping, decoding, MQTT/API requests and diagnostics are
shared with the [single-port driver](rs485-modbus.md). Every entity's `port`
must match a configured name; omitted values select `ch0`.

## State, responses and diagnostics

All entity values are combined into one module state payload. Ad-hoc commands
select a port explicitly and correlated results use the configured module
response topic. Diagnostics identify the port, operation, address, latency and
last error so a failing bus can be separated from healthy ports.

Each port must use an available UART and non-conflicting TX/RX/DE pins. Do not
electrically join independently biased/isolated ports. Capacity planning must
account for the sum of every entity's poll rate on each port.
