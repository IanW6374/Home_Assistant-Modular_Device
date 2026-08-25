# EMS Boiler

## Purpose and configuration

Use `class: sensor` and `subclass: EMS-Boiler` for read-only Bosch/Buderus EMS
and EMS+ monitoring. The `ems` object supports `uart`, `tx`, `rx`, `baudrate`,
framing, `frame_gap_ms`, `poll_ms`, receive limits and `debug_frames`; the
defaults are UART 1, GPIO 17/18 and 9600 8N1. `boiler_id` defaults to 8.

Only configured entity keys are published. Supported monitor telegrams expose
flow/return/DHW temperatures, demand and flame states, burner/pump data,
pressure, service codes and runtime counters. Diagnostic keys include last
source/type, frame and CRC counts, breaks, overflows and detected EMS family.
Verbose frame logging can be toggled from **Module > Diagnostics** and should be
left off during normal operation.

## State and integrations

The module publishes one JSON object keyed by the configured telegram fields.
The same read-only state is available over MQTT, the Device API and optional HA
discovery. No command can alter boiler operation: the driver does not
acknowledge polls, originate telegrams or write settings.

## Wiring and troubleshooting

Start from the [EMS example](../../examples/module_settings.ems.example.json).
Connect through a purpose-built isolated EMS interface presenting safe 3.3 V
UART signals; never connect the ESP32 directly to the boiler bus. If frame count
increases but CRC/decoded values do not, verify polarity, baud/framing and the
interface. If no frames arrive, verify RX pin and physical interface power.
Enable frame debug only temporarily because it is deliberately verbose.
