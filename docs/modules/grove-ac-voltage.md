# Grove AC Voltage

## Hardware and configuration

Use `class: sensor` and `subclass: Grove-AC-Voltage`. The `ac_voltage` object
selects `adc_pin` and controls RMS sampling (`vref`, `adc_max`, `sample_count`,
`sample_delay_us`), conversion (`calibration`, `offset`, `precision`) and the
optional presence threshold (`threshold`, `hysteresis`, `threshold_key`). The
defaults are GPIO 26, 600 samples, 200 µs spacing, calibration 700, a 180 V
threshold and 5 V hysteresis. `pollinterval` defaults to five seconds.

The main `voltage` entity can be accompanied by `ac_present`, ADC and error
diagnostics. Calibrate from **Module > Diagnostics** using a trusted meter; the
calculated multiplier is persisted with module configuration. Start from the complete
[example configuration](../../examples/module_settings.grove_ac_voltage.example.json).

## State, commands and diagnostics

State resembles `{"voltage":230.4,"ac_present":true}` and is identical over
MQTT, API and optional HA discovery. Calibration commands are privileged module
operations; ordinary clients should treat the module as read-only. Hysteresis
prevents presence chatter around the threshold. Diagnostics expose raw ADC/RMS,
calibration and sampling errors.

This module measures mains-derived signals. Use only an appropriately isolated,
rated sensor assembly, fusing and enclosure. IoTMD readings are operational,
not certified revenue or protective measurements.
