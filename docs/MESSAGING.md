# MQTT messaging and Home Assistant

IoT-MD treats MQTT as a platform-neutral transport. Home Assistant discovery is
an optional integration layered over the same secure broker connection. Both
are configured under **System > Messaging**.

## Connection and security

Enable MQTT, enter the broker host and TLS port, and install the broker CA under
**Maintenance > Certificates**. TLS is mandatory and authenticates the broker;
IoT-MD does not currently present an MQTT client certificate. Username and
password are optional only when the broker deliberately permits a client
without them. QoS can be 0 or 1.

The exact value entered as **Broker hostname** is passed to TLS for identity
verification. It must appear in the certificate's Subject Alternative Name
(SAN) as a `DNS` name, or as an `IP Address` when an IP literal is configured.
If any SAN extension is present, a matching Common Name alone is not enough.
The MQTT trusted CA establishes the issuer chain; it does not disable or replace
hostname verification. After changing a broker certificate, restart/reload the
broker and confirm that it presents the new leaf and intermediate chain.

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

Selecting **Enable Home Assistant Discovery Integration** publishes MQTT discovery under
the configured discovery prefix (`homeassistant` by default) and subscribes to
Home Assistant's status topic so discovery is republished after HA restarts.
Discovery payloads point at the administrator-defined operational topics; Home
Assistant does not require the operational base to be `homeassistant` or
`iotmd`.

Disabling the profile leaves generic MQTT telemetry and commands operational.
It stops discovery publication and the Home Assistant status subscription. Use
**Publish discovery** after changing entity metadata or restoring an HA
instance.

## Retained state

The device availability payload is always retained. **Retain module state by
default** sets the MQTT retain flag on module state publications, causing the
broker to store the latest value for each state topic and send it immediately
to new subscribers. This prevents a newly connected Home Assistant or generic
client from waiting for the next module poll.

A module-level `retain_state` value overrides the global setting. Retention does
not preserve GPIO output state, driver memory or runtime energy counters across
an IoT-MD restart. Commands must never be retained because a broker could replay
an obsolete action when the device reconnects. When permanently changing a
module UUID or topic template, remove any obsolete retained state from the
broker if consumers should no longer see it.

## Delivery behaviour

Publishing is bounded to protect the ESP32-S3 heap. Health history counts queue
drops, failures and reconnects. QoS 1 confirms broker receipt but does not make
commands idempotent; clients should supply their own `request_id` where the
driver supports it. Retained command messages should not be used.

Troubleshoot in this order: confirm time synchronization, the configured broker
hostname, certificate DNS/IP SANs and chain, DNS resolution, broker reachability,
credentials, then the resolved topics shown in module diagnostics. To inspect
the identity actually presented by a broker, use the configured name for both
SNI and verification, for example:

```sh
openssl s_client -connect mqtt-broker.home.arpa:8883 \
  -servername mqtt-broker.home.arpa -verify_hostname mqtt-broker.home.arpa \
  </dev/null
```

Debug logging records MQTT routing without exposing passwords.
