# Rotary dimmer input

Use `class: switch` and `subclass: dimmer` for a quadrature rotary encoder with
push switch. Configure `gpio.input.clk`, `.dt`, and `.sw`. All inputs use
pull-ups; connect the encoder common and switch return to ground. Rotation and
button activity control the locally linked output and are not separate Home
Assistant entities.

Keep encoder leads short or add hardware debouncing in electrically noisy
installations.
