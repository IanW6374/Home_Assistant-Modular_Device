# IoT-MD v3.0.0-alpha.4 test note

## Purpose

Alpha 4 introduces the transport-independent product-service layer. It builds
on the successfully installed Alpha 3 kernel while retaining the v2.5
compatibility runtime as the active portal, MQTT and Device API implementation
during qualification.

## Included

- Runtime configuration contract version 2 with bounded product transports,
  explicit dependencies, criticality and non-mutating migration from Alpha 3.
- A Wi-Fi lifecycle service and injected adapters for MQTT, the server-rendered
  portal and Device API v3. Socket, TLS and MQTT client objects do not cross
  into domain services.
- Mandatory verified-client and `read`-scope enforcement for the mTLS Device
  API, with small device, health, service and connectivity projections.
- Bounded MQTT state and optional Home Assistant discovery publication.
- Role-aware HTML generated from shared navigation and form metadata.
- One rotating diagnostic service for DNS, time, TLS, MQTT, CA, syslog and
  release connectivity. Probe failures expose only an exception class, never
  the potentially sensitive exception message.
- Live browser byte progress for manual upgrade chunks. Resumable transport
  hashing is now labelled separately from signed application verification so
  the application no longer appears to be verified twice.

## Deliberately incomplete

- The Alpha 4 adapters have host contract coverage but are not yet the product
  entry point. The compatibility runtime continues to serve real traffic.
- Certificate enrollment, renewal, fleet policy and v2 migration remain Alpha
  5 scope.
- Native paired partition control, rollback and USB NCM remain capability-gated
  off until their separate hardware gates pass.

## Safety and rollback

The release sequence is `2709`. Install only on a recoverable test device.
Returning to an older sequence can require USB recovery or a later signed
release with a higher sequence.

## Hardware checks

1. Upload the universal package and confirm the percentage increases during
   the initial browser-to-device transfer.
2. Confirm the status distinguishes checking uploaded component bytes from
   verifying the signed application; only one signed-application verification
   phase should be shown.
3. After activation, confirm the compatibility portal, MQTT connection and
   Device API continue to operate as they did in Alpha 3.
4. From USB, import the Alpha 4 modules and instantiate the adapters with test
   doubles or the HIL harness. Confirm Wi-Fi starts before dependent services,
   the API denies an unverified client, and all seven connectivity probes
   complete without leaking endpoint credentials.

The Alpha 4 exit gate additionally requires portal/API/MQTT behavior and mTLS,
disconnect/reconnect, DNS failure and broker outage HIL results against the v3
requirements baseline.
