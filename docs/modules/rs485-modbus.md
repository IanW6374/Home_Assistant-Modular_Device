# RS485 Modbus

Use `class: sensor` and `subclass: RS485-Modbus` for one Modbus RTU port named
`ch0`. The `rs485` object supports `uart`, `tx`, `rx`, optional half-duplex
`de`, `baudrate`, `bits`, `parity`, `stop`, `tx_enable_active`,
`turnaround_ms`, `timeout_ms`, and `max_group_registers`.

Each polled entity defines `slave`, `function`, `address`, `count`, `data_type`,
optional byte/word order, `scale`, `offset`, and `pollinterval`. Supported codec
types include signed/unsigned integer widths, floating point and ASCII. Adjacent
compatible registers are grouped to reduce bus traffic. MQTT `/set` also accepts
ad-hoc read and write requests and returns correlated results on `/response`.
Diagnostics report the last operation, address, error and latency.

Start from the [single-port example](../../examples/module_settings_rs485.json).
Use a 3.3 V-compatible isolated transceiver and correct bus termination/biasing.
