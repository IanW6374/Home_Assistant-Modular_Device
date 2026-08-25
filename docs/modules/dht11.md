# DHT11 temperature and humidity

Use `class: sensor` and `subclass: dht11`. Configure `gpio.input.0` as the DHT11
data pin and add `temperature` and/or `humidity` entities with their units and
initial `value`. `pollinterval` defaults to 60 seconds. Each successful reading
updates the shared MQTT state payload and Home Assistant discovery entities.

Power the sensor at a compatible voltage and fit the data-line pull-up required
by the particular module board. The DHT11 is a low-accuracy ambient sensor; do
not use it for safety or process control.
