# Grove AC Voltage

Use `class: sensor` and `subclass: Grove-AC-Voltage`. The `ac_voltage` object
selects `adc_pin` and controls RMS sampling (`vref`, `adc_max`, `sample_count`,
`sample_delay_us`), conversion (`calibration`, `offset`, `precision`) and the
optional presence threshold (`threshold`, `hysteresis`, `threshold_key`). The
defaults are 600 samples, 200 µs spacing, calibration 700, a 180 V threshold
and 5 V hysteresis.

The main `voltage` entity can be accompanied by an `ac_present` binary sensor
and ADC/error diagnostics. Calibrate from **Module > Diagnostics** using a
trusted meter reading; the calculated multiplier is persisted with module
configuration. Start from the complete
[example configuration](../../examples/module_settings.grove_ac_voltage.example.json).

This module measures mains-derived signals. Use only an appropriately isolated,
rated sensor assembly and enclosure.
