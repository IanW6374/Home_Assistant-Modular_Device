# Feature flags and network transports

IoT-MD v2.5 resolves optional behavior in one `FeatureFlags` registry. A feature
is enabled only when every required input agrees:

1. signed `app_settings.json` policy requests it;
2. the firmware build includes it;
3. the configured release channel permits it; and
4. runtime capability detection confirms the required API or hardware.

The Device API and support data expose the requested state, effective state and
reason for every flag. Code must not infer a feature from the product,
MicroPython or ESP-IDF version alone.

| Flag | Default | Additional gate |
| --- | --- | --- |
| `transport_independent_api` | Enabled | None |
| `split_api_payloads` | Enabled | None |
| `hardware_resource_manager` | Enabled | None |
| `usb_ncm` | Disabled | Beta/development channel and validated platform capability |
| `tls_session_resumption` | Disabled | Beta/development channel and stable runtime session API |

## Transport-independent API

The API router receives `APIRequest` and returns `APIResponse`. HTTPS/mTLS is a
concrete adapter and remains mandatory for network access. This separation does
not weaken authentication: an alternative transport must provide the same peer
identity and remains subject to the existing fingerprint registry and scopes.

The HTTPS listener binds to the configured IP host (normally `0.0.0.0`), so one
listener can accept traffic arriving over Wi-Fi or an enabled lwIP network
interface. Ethernet is an architectural extension point, not a supported board
interface in this release.

## Experimental USB NCM

### Finding

MicroPython v1.29 provides the generic `network.USBD_NCM` implementation. The
ESP32-S3 has native USB OTG hardware and Espressif's ESP-IDF/TinyUSB stack can
provide NCM. Development builds can enumerate the board as an NCM device, but
the resulting interface is not functional through MicroPython's ESP32 network
port. This is an integration limitation, not a hardware limitation.

### Technical Cause

The generic driver assumes MicroPython's generic lwIP networking model. The
ESP32 port instead uses ESP-IDF-managed networking and does not use
`MICROPY_PY_LWIP` like the RP2 and STM32 ports. Its network locking, NIC
registration, IP configuration, mDNS and pinned TinyUSB interfaces therefore
do not satisfy the generic driver's assumptions. Defining
`MICROPY_PY_NETWORK_USBD_NCM` can produce USB enumeration without a usable
network interface and is not evidence of production support.

### Decision for v1.29

The v2.5 application includes the USB NCM transport contract, lifecycle and
capability detection, but the ESP32-S3 board build keeps
`MICROPY_PY_NETWORK_USBD_NCM` disabled. MicroPython 1.29's generic NCM driver is
not yet integrated with the ESP32 port's network locking, NIC registration and
TinyUSB APIs. The effective feature therefore reports unavailable on this core.
Setup, Wi-Fi operation, update confirmation and recovery do not depend on USB
networking.

Capability reporting separates `usb_device`, `usb_ncm_hardware`,
`usb_ncm_runtime` and `usb_ncm_available`. For ESP32-S3 on the qualified v1.29
core the first two are true, while port compatibility and effective NCM
availability are false. The presence of `network.USBD_NCM` alone can never
enable the feature.

### Future Opportunity

USB NCM may be introduced by a future upstream MicroPython ESP32 integration or
by an IoT-MD-specific ESP-IDF/TinyUSB backend in a separately qualified alpha
firmware. Either route must pass USB enumeration, packet transfer, DHCP,
reconnect, host compatibility, TLS, recovery, resource and update testing
before the platform capability is marked available.

After a compatible ESP32 core is qualified, explicitly enabling the feature in
a beta/development policy will expose a USB NCM adapter and its deterministic
`169.254.x.1/16` address under `GET /api/v2/interfaces`. The implementation
does not perform RFC 3927 address-conflict detection, so USB NCM must not be
bridged into an untrusted or multi-device segment. The same portal/API TLS and
authentication policy will still apply; USB is a network path, not an
authentication bypass.

### Recommended Architecture

Keep `NetworkTransport`, `APIRequest` and `APIResponse` independent of Wi-Fi,
USB and ESP-IDF. Resolve NCM availability from hardware support, runtime/API
support, ESP32 port compatibility, firmware build configuration and signed
IoT-MD feature policy. When a backend is qualified, only the platform/transport
implementation and its capability declaration should change; REST routes,
services, certificate policy and authorization must remain unchanged.

## TLS session seam

Outbound release and TLS syslog connections accept an opaque
`TLSSessionHandle`. MicroPython 1.29 exposes no stable uasyncio session API, so
the handle is ignored and the effective `tls_session_resumption` flag remains
off. This preserves a transport contract for a later qualified runtime without
exposing a port-specific SSL object or claiming a performance feature that is
not present.
