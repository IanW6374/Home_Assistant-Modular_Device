# Module guide

Modules are configured as entries in `module_settings.json` or through **Module
> Configuration** in the device portal. Every entry needs a unique four-digit
hexadecimal `uuid`, a `name`, a supported `type`, and an `entities` object. The
configuration is validated against
[`module_settings.schema.json`](../../module_settings.schema.json) before it is
committed.

## Supported types

| Class | Subclass | Guide |
| --- | --- | --- |
| `light` | `onoff` | [On/off light](light-onoff.md) |
| `light` | `brightness` | [Brightness light](light-brightness.md) |
| `light` | `rgb` | [RGB light](light-rgb.md) |
| `switch` | `onoff` | [On/off switch input](switch-onoff.md) |
| `switch` | `dimmer` | [Rotary dimmer input](switch-dimmer.md) |
| `sensor` | `dht11` | [DHT11](dht11.md) |
| `sensor` | `hcsr04` | [HCSR04](hcsr04.md) |
| `sensor` | `Grove-AC-Voltage` | [Grove AC Voltage](grove-ac-voltage.md) |
| `sensor` | `MAX31865-PT1000` | [MAX31865 PT1000](max31865-pt1000.md) |
| `sensor` | `RS485-Modbus` | [RS485 Modbus](rs485-modbus.md) |
| `sensor` | `RS485-Modbus-Multiport` | [Multiport Modbus](rs485-modbus-multiport.md) |
| `sensor` | `WHES` | [WHES inverter](whes.md) |
| `sensor` | `EMS-Boiler` | [EMS Boiler](ems-boiler.md) |

GPIO numbers are ESP32-S3 GPIO numbers, not header positions. Do not assign a
pin, UART or SPI bus to more than one module. The portal resource validator
reports conflicts before restart. After applying a change, use **Module >
Diagnostics** to confirm values and driver health.
