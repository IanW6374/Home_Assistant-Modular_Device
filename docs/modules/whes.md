# WHES inverter

Use `class: sensor` and `subclass: WHES` for the WHES inverter register map over
the single `ch0` RS485 transport. Configure the bus in `rs485`; the supplied
example uses UART 1, GPIO 17/18, GPIO 16 for DE and 115200 baud. The configured
raw registers include inverter identity, status, temperatures, PV channels,
grid/battery power and battery state of charge.

The driver publishes a stable Home Assistant presentation including PV,
battery, grid and calculated home power, daily import/export/charge/discharge
energy, inverter metadata, and RS485 diagnostics. Daily calculated energy
counters reset using the configured device time zone and are runtime totals,
not billing-grade meter readings.

Use the complete [WHES example](../../examples/module_settings.whes.example.json)
as the register-map baseline and change pins or serial identity only as needed.
