# Rotary dimmer input

## Hardware and configuration

Use `class: switch` and `subclass: dimmer` for a quadrature encoder with push
switch. Configure `gpio.input.clk`, `.dt` and `.sw`. Inputs use pull-ups; connect
the common and switch return to ground. Use dry contacts and keep leads short.

## Behaviour and state

Rotation adjusts the locally linked brightness/RGB output and the push switch
toggles it. These controls continue locally when MQTT or Home Assistant is
offline and are not separate HA entities. Output state changes are published by
the controlled light through its normal configured state topic/API state.

## Diagnostics

Diagnostics show encoder/button activity and allocation conflicts. Reversed
rotation is corrected by swapping CLK and DT. Skipped or extra steps usually
require shorter wiring, shielding/grounding or hardware debounce in noisy
installations.
