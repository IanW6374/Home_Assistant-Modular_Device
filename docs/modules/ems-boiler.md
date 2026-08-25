# EMS Boiler

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

Start from the [EMS example](../../examples/module_settings.ems.example.json).
The driver is deliberately passive: it does not acknowledge polls or write
boiler settings. Connect through a purpose-built isolated EMS interface that
presents a safe 3.3 V UART; never connect the ESP32 directly to the boiler bus.
