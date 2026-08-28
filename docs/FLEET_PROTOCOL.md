# IoT-MD fleet protocol v1

The independently released
[IoT-MD Fleet Manager](https://github.com/IanW6374/IoTMD-Home-Assistant-Addons)
uses the device's `/api/v2` endpoints over mandatory mutual TLS.

## Identity and inventory

Fleet clients use dedicated certificates with `fleet:read` and optional
`fleet:write` scopes. Device identity is the immutable factory identifier plus
certificate identity; hostnames are display and routing attributes.

Inventory reports product, application/core versions, release sequences,
board, capabilities, drivers, health, clock and update state. It never returns
credentials, private keys or password verifiers.

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
