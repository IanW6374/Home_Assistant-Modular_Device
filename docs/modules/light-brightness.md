# Brightness light

## Hardware and configuration

Use `class: light` and `subclass: brightness` for one PWM channel. Configure
`gpio.output.0`, `gpio.pwm_freq` and `gpio.activeHigh`. Choose a frequency
supported by the external LED driver; the ESP32 GPIO supplies only its
logic-level control input.

## State and commands

The entity stores `state` and integer `brightness` from 0 to 255:

```json
{"state":"ON","brightness":192}
```

Publish that object to the configured command topic or POST it through the
module command API. `OFF` disables the output without discarding the remembered
brightness. Home Assistant discovery advertises brightness mode when enabled.

## Diagnostics

Use diagnostics to confirm pin allocation and command/state changes. Flicker
usually means an unsuitable PWM frequency, inadequate driver power, grounding
problems or a pin conflict. Test active-low hardware before connecting the load.
