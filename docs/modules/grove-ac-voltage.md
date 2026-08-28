# Grove AC Voltage

## Hardware and configuration

Use `class: sensor` and `subclass: Grove-AC-Voltage`. The `ac_voltage` object
selects `adc_pin` and controls RMS sampling (`vref`, `adc_max`, `sample_count`,
`sample_delay_us`), conversion (`calibration`, `offset`, `precision`) and the
optional presence threshold (`threshold`, `hysteresis`, `threshold_key`). The
sampling defaults are 600 samples, 200 µs spacing, calibration 700, a 180 V
threshold and 5 V hysteresis. `pollinterval` defaults to five seconds.

Always configure `adc_pin` explicitly for the production
ESP32-S3-DevKitC-1-N8R8. The driver's legacy GPIO 26 fallback is not suitable
for that board because its octal flash/PSRAM reserves GPIO 26. The standalone
example uses ADC-capable GPIO 1; the HTW example uses GPIO 4. Confirm the chosen
pin against the board schematic and every other configured module.

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
rated sensor assembly, fusing and enclosure. IoT-MD readings are operational,
not certified revenue or protective measurements.
