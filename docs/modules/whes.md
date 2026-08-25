# WHES inverter

## Configuration and transport

Use `class: sensor` and `subclass: WHES` for the WHES inverter register map over
the single `ch0` RS485 transport. Configure the bus in `rs485`; the supplied
example uses UART 1, GPIO 17/18, GPIO 16 for DE and 115200 baud. The configured
raw registers include inverter identity, status, temperatures, PV channels,
grid/battery power and battery state of charge.

The driver publishes a stable transport-neutral presentation including PV,
battery, grid and calculated home power, daily import/export/charge/discharge
energy, inverter metadata and RS485 diagnostics. MQTT and API return the same
keys; optional Home Assistant discovery adds the corresponding entities.

## Power sign and calculation assumptions

The presentation is derived from the configured raw register keys:

```text
PV_p      = Ppv1 + Ppv2
battery_p = -BatPower_BMS
grid_p    = Power_Meter
home_p    = dwPower_HomeLoad, when present
home_p    = PV_p + battery_p + grid_p, otherwise
```

Positive `battery_p` means discharge and negative means charge. Positive
`grid_p` means import and negative means export. Charge/discharge and
import/export helper powers are the positive magnitude of the applicable
direction; the opposite direction is zero. Confirm the inverter/CT installation
uses these signs before relying on the presentation.

## Runtime energy integration

The six daily counters integrate non-negative source power using:

```text
increment_kWh = max(power_W, 0) * elapsed_ms / 3,600,000,000
```

PV, home load, battery charge/discharge and grid import/export are integrated
independently, rounded to four decimal places for publication, and reset at
local midnight using the configured IANA time zone. They start from zero after
application restart and do not persist across restarts. Sampling gaps, register
latency and clock changes affect them; they are operational estimates, not
billing-grade meter readings.

## Diagnostics and safety

Use the complete [WHES example](../../examples/module_settings.whes.example.json)
as the register-map baseline and change pins or serial identity only as needed.
Use `rs485_last_ok`, operation, address, error and latency to diagnose bus
failures. Check CT orientation and raw register values when calculated flows are
implausible. Inverter control/protection remains the responsibility of approved
manufacturer equipment and settings.
