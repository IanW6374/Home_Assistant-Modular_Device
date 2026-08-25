# HCSR04 ultrasonic distance

Use `class: sensor` and `subclass: hcsr04`. Configure `gpio.input.trig` and
`gpio.input.echo`; add a `distance` entity, normally with `cm` as its unit.
`pollinterval` defaults to 60 seconds and the echo timeout is 10,000 µs.

The common HC-SR04 echo output is 5 V. Use a voltage divider or level shifter so
the ESP32-S3 GPIO never receives more than 3.3 V. The published value is the
distance returned by the bundled HCSR04 library.
