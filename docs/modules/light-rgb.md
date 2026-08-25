# RGB light

Use `class: light` and `subclass: rgb` for three PWM channels. Configure
`gpio.output.r`, `.g`, and `.b`, plus `gpio.pwm_freq` and `gpio.activeHigh`.
The entity contains `state`, `brightness` (0–255), and
`color: {"r":0,"g":0,"b":0}`. Home Assistant sends the same JSON structure
to the module `/set` topic.

Each channel needs an appropriate external driver. All three pins use the same
configured PWM frequency.
