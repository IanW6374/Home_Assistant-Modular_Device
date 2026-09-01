# IoT-MD fleet protocol v1

The independently released
[IoT-MD Management Suite](https://github.com/IanW6374/HA-IoT-MD-Management-Suite)
uses the device's `/api/v2` endpoints over mandatory mutual TLS.

## Identity and inventory

Fleet clients use dedicated certificates with `fleet:read` and optional
`fleet:write` scopes. Device identity is the immutable factory identifier plus
certificate identity; hostnames are display and routing attributes.

The combined inventory route remains available for existing managers. New
fleet clients should use `/api/v2/device`, `/interfaces`, `/hardware`, and
`/services`, retrieving module catalog and health only when required. This
reduces peak device JSON allocation while reporting the same product,
application/core versions, release sequences, board, capabilities, drivers,
health and transport state. `/api/v2/configuration` contains only a bounded
non-secret operating summary. No endpoint returns credentials, private keys or
password verifiers.

## Signed policy

Fleet policy has an independent ECDSA P-256 key. The manager stores the private
key and devices store only the 64-byte public key. A policy binds:

- sequence, issue time, validity window, device/cohort and target board;
- local maintenance days, start time and duration;
- update channel, download/activation controls and failure threshold;
- telemetry interval/severity and bounded command identifiers.

Devices reject invalid signatures, replayed sequences, incorrect targets,
expired policies, unknown fields and policies requiring an unsynchronised
clock. Fleet policy can select signed releases but cannot create firmware.

## Events and rollouts

Events use a monotonic cursor and explicitly report retention gaps. Rollouts
advance through ordered cohorts only after required success results and stop at
their configured failure threshold. Rollback references a previously confirmed
signed release.
