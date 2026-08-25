# Brightness light

Use `class: light` and `subclass: brightness` for a single-channel PWM light.
Configure `gpio.output.0`, `gpio.pwm_freq`, and `gpio.activeHigh`. The entity
stores `state` and an integer `brightness` from 0 to 255; both are accepted in
the JSON `/set` payload. Home Assistant discovery advertises brightness mode.

Choose a PWM frequency suitable for the external LED driver. The GPIO must
drive a logic-level interface rather than the load directly.
