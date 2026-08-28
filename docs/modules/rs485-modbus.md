# RS485 Modbus

## Port and entity configuration

Use `class: sensor` and `subclass: RS485-Modbus` for one Modbus RTU port named
`ch0`. The `rs485` object supports `uart`, `tx`, `rx`, optional half-duplex
`de`, `baudrate`, `bits`, `parity`, `stop`, `tx_enable_active`,
`turnaround_ms`, `timeout_ms`, and `max_group_registers`.

Each polled entity defines `slave`, `function`, `address`, `count`, `data_type`,
optional byte/word order, `scale`, `offset`, and `pollinterval`. Supported codec
types include signed/unsigned 16/32/64-bit values, floating point and ASCII. Adjacent
compatible registers are grouped to reduce bus traffic. MQTT `/set` also accepts
ad-hoc read and write requests and returns correlated results on `/response`.
Diagnostics report the last operation, address, error and latency.

## Ad-hoc request contract

Send a JSON object to the configured command topic or module command API:

```json
{"request_id":"r-42","operation":"read","port":"ch0","slave":1,
 "function":4,"address":36155,"count":1,"data_type":"uint16","scale":0.1}
```

Writes use `operation: "write"` plus `value`, type and scaling. The asynchronous
result includes `request_id` and is published on the configured response topic;
the API operation also reports completion. Validate writes against the target
manufacturer's register map—IoT-MD cannot determine whether a writable register
is operationally safe.

## Wiring and troubleshooting

Start from the [single-port example](../../examples/module_settings_rs485.json).
Use a 3.3 V-compatible isolated transceiver and correct bus termination/biasing.
Only the physical ends of a long bus should be terminated. Confirm A/B polarity,
common reference, slave ID, serial framing and register base (zero- versus
one-based documentation). CRC/timeouts and last latency are available in module
diagnostics. Avoid overlapping polls that exceed the configured RTU bandwidth.
