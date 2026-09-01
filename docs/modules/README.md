# Module guide

Modules are configured as entries in `module_settings.json` or through **Module
> Configuration** in the device portal. Every entry needs a unique four-digit
hexadecimal `uuid`, a `name`, a supported `type`, and an `entities` object. The
configuration is validated against
[`module_settings.schema.json`](../../module_settings.schema.json) before it is
committed.

## Common contract

Each module has one transport-neutral state object. It is published to the
administrator-defined MQTT state topic and returned by
`GET /api/v2/modules/{uuid}/state`. Writable drivers accept the same JSON command
body through the configured MQTT command topic or
`POST /api/v2/modules/{uuid}/commands`. Diagnostics are available in the portal
and at `/api/v2/modules/{uuid}/diagnostics`. See the
[messaging](../MESSAGING.md) and [API](../API.md) guides.

Home Assistant discovery is optional. Enabling it adds an HA presentation for
the same state and command topics; it does not change the driver or payload.
Entity `class`, `device_class`, `unit`, `state_class` and `entity_category`
control that presentation.

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

GPIO numbers are ESP32-S3 GPIO numbers, not header positions. The central
resource manager maps owner-qualified logical names (for example
`00A1.max31865.spi`) to physical GPIO, ADC, UART and SPI resources before any
driver is created. Do not assign an exclusive pin or UART to more than one
module. Shared SPI buses are allowed only when their pins and electrical mode
match; each device retains its own chip select. The portal validator reports
conflicts before restart, and `/api/v2/hardware` exposes the effective binding
catalog. Resource-aware drivers receive an owner-scoped acquisition interface;
they cannot acquire another module's declaration. After applying a change, use
**Module > Diagnostics** to confirm values and driver health.

Use unique UUIDs permanently: changing a UUID changes MQTT topics, API identity
and Home Assistant unique IDs. A module-level `retain_state` overrides the
global MQTT setting. It controls the MQTT retain flag for that module's
state publication so new subscribers receive the broker's last value; it does
not persist driver memory or physical output state across a device restart.
Never retain command messages. Poll intervals are seconds unless a driver
explicitly names a millisecond field. Treat all mains, boiler, inverter and
high-current connections as hardware engineering work requiring appropriate
isolation, protection and enclosure.
