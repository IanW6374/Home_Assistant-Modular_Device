# MQTT messaging and Home Assistant

IoTMD treats MQTT as a platform-neutral transport. Home Assistant discovery is
an optional integration layered over the same secure broker connection. Both
are configured under **System > Messaging**.

## Connection and security

Enable MQTT, enter the broker host and TLS port, and install the broker CA under
**Maintenance > Certificates**. TLS is mandatory. Username and password are
optional if the broker authenticates the device certificate. QoS can be 0 or 1.
The device availability payload is retained; module state retention is an
administrator setting and can be overridden per module with `retain_state`.

## Topic templates

The defaults are deliberately independent of Home Assistant:

| Purpose | Default |
| --- | --- |
| Base | `iotmd` |
| State | `{base}/{device_id}/{module_id}/state` |
| Command | `{base}/{device_id}/{module_id}/set` |
| Response | `{base}/{device_id}/{module_id}/response` |
| Availability | `{base}/{device_id}/availability` |

Available placeholders are `{base}`, `{device_id}`, `{module_id}` and
`{component}`. State, command and response templates must include both device
and module IDs; availability must include the device ID. Wildcards (`+`, `#`),
empty path segments and unknown placeholders are rejected. The device ID is the
hardware identifier plus the portal-safe device name. The module ID is its
four-digit configured UUID.

Example state message:

```text
iotmd/7c9e_bd-controller/00A1/state
{"temperature":21.7,"humidity":48}
```

Commands are JSON objects appropriate to the driver. Disable **Subscribe to
command topics** for telemetry-only installations. Drivers that perform an
asynchronous request, such as Modbus, publish the correlated result on the
configured response topic.

## Home Assistant profile

Selecting **Enable Home Assistant integration** publishes MQTT discovery under
the configured discovery prefix (`homeassistant` by default) and subscribes to
Home Assistant's status topic so discovery is republished after HA restarts.
Discovery payloads point at the administrator-defined operational topics; Home
Assistant does not require the operational base to be `homeassistant` or
`iotmd`.

Disabling the profile leaves generic MQTT telemetry and commands operational.
It stops discovery publication and the Home Assistant status subscription. Use
**Republish discovery** after changing entity metadata or restoring an HA
instance.

## Delivery behaviour

Publishing is bounded to protect the ESP32-S3 heap. Health history counts queue
drops, failures and reconnects. QoS 1 confirms broker receipt but does not make
commands idempotent; clients should supply their own `request_id` where the
driver supports it. Retained command messages should not be used.

Troubleshoot in this order: confirm time synchronization, certificate validity,
DNS, broker reachability, credentials, then the resolved topics shown in module
diagnostics. Debug logging records MQTT routing without exposing passwords.
