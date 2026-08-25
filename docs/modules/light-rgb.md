# RGB light

## Hardware and configuration

Use `class: light` and `subclass: rgb`. Configure `gpio.output.r`, `.g` and `.b`,
plus shared `gpio.pwm_freq` and `gpio.activeHigh`. Each channel requires an
appropriately rated external driver. Confirm whether the fixture is common
anode (normally active-low) or common cathode (normally active-high).

## State and commands

```json
{"state":"ON","brightness":180,"color":{"r":255,"g":80,"b":0}}
```

Brightness and each colour component are integers from 0 to 255. The same body
is accepted by MQTT and the module command API; omitted fields retain their
current values. Home Assistant discovery enables RGB and brightness features.

## Diagnostics

Diagnostics expose allocation and command health. Swapped colours indicate pin
mapping; incorrect inversion produces reversed brightness. Uneven colour or
resets under load indicate the external power/driver design, not a software
calibration facility.
