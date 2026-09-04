# Device API v2

The Device API is a JSON HTTPS interface for inventory, state, diagnostics,
commands, events, support data and fleet coordination. It listens on port 8444
by default and always requires mutual TLS. The machine-readable contract is
[`openapi.yaml`](openapi.yaml).

From v2.5 the router consumes transport-neutral `APIRequest` objects and returns
`APIResponse` objects. HTTPS/mTLS remains the supported external adapter; this
internal separation does not create an unauthenticated API. A listener bound to
`0.0.0.0` can serve any policy-enabled lwIP interface, including experimental
USB NCM, using the same certificate registry and scopes.

Its server certificate is stored independently from the web portal identity
and is expected to chain to the private IoT CA. A public portal renewal never
changes the Device API/fleet server identity.

## TLS identities and trust

Mutual TLS performs two independent checks:

- IoT-MD authenticates the client certificate against an installed API-client
  CA, then applies the fingerprint registration and scopes described below.
- The API client authenticates IoT-MD against its private IoT CA. The API
  server certificate must contain the exact device hostname, such as
  `iot-md-001.local`, in a DNS Subject Alternative Name (SAN).

The client certificate and key supplied to `curl` prove the caller's identity;
they do not make the workstation trust the server. Supply the private IoT CA
root, plus any required intermediate, with `--cacert`. IoT-MD installs its API
server identity as a leaf-plus-intermediate chain, but using a complete CA
bundle on the client also supports diagnostic and older installations. Do not
use `-k` to bypass verification.

## Authentication and authorization

Install one or more API client CAs under **Maintenance > Certificates > API
client trust**, then
enable the listener under **Device > Device API**. Each client certificate is
registered by SHA-256 fingerprint with a label and scopes. Read requests require
`read`, module commands require `write`, fleet reads require `fleet:read`, and
fleet changes require `fleet:write`. Revocation is checked for every request,
including requests on reused TLS connections.

The API accepts up to 32 requests on one HTTP/1.1 keep-alive connection and
holds an idle connection for at most 30 seconds. Reuse the connection: a TLS
handshake is substantially more expensive than a JSON request on ESP32-S3.

## Endpoints

| Method | Path | Scope | Result |
| --- | --- | --- | --- |
| GET | `/api/v2/device` | `read` | Identity, versions, uptime, release sequences and bounded release-qualification state |
| GET | `/api/v2/interfaces` | `read` | Wi-Fi, MQTT, API, syslog and USB NCM state |
| GET | `/api/v2/hardware` | `read` | Board, runtime capability, USB/NCM gates, drivers and resource bindings |
| GET | `/api/v2/services` | `read` | Lifecycle, boot and effective feature-flag state |
| GET | `/api/v2/configuration` | `read` | Bounded non-secret operating configuration |
| GET | `/api/v2/device/inventory` | `read` | Compatibility combined device, module and fleet inventory |
| GET | `/api/v2/health` | `read` | Bounded health counters and observations |
| GET | `/api/v2/events?cursor=0&limit=32` | `read` | Cursor-based event page |
| GET | `/api/v2/support` | `read` | Redacted support snapshot |
| GET | `/api/v2/modules` | `read` | Module catalog and capabilities |
| GET | `/api/v2/modules/{uuid}/state` | `read` | Current transport-neutral state |
| GET | `/api/v2/modules/{uuid}/diagnostics` | `read` | Driver diagnostics |
| POST | `/api/v2/modules/{uuid}/commands` | `write` | Queued operation (`202`) |
| GET | `/api/v2/operations/{id}` | `read` | Operation status |
| GET | `/api/v2/fleet` | `fleet:read` | Fleet enrollment and policy state |
| POST | `/api/v2/fleet/policy` | `fleet:write` | Apply a monotonic signed policy |
| POST | `/api/v2/fleet/commands/{id}/result` | `fleet:write` | Complete a fleet command |

UUIDs are the configured four-digit hexadecimal module IDs. State keys and
command bodies are driver-specific and are documented in the
[module guide](modules/README.md). A command returns an operation record
immediately; poll its URL until `status` is `complete` or `failed`.

## Example

```sh
cat home-iot-intermediate.pem home-iot-root.pem > home-iot-ca-bundle.pem

curl --fail-with-body \
  --cacert home-iot-ca-bundle.pem \
  --cert api-client.pem \
  --key api-client-key.pem \
  https://iot-md-001.local:8444/api/v2/modules/00A1/state
```

```json
{"module":"00A1","state":{"temperature":21.7,"humidity":48}}
```

Routine GETs increment aggregate counters but are logged only at debug level;
mutating calls create health and audit records. Responses are `no-store` JSON.
Typical failures are `400` malformed input, `401` missing/invalid identity,
`403` insufficient scope, `404` unknown endpoint/module/operation, `413`
oversized input and `503` temporarily unavailable service.

New clients should request only the smaller projection they need. The combined
inventory endpoint is retained for existing management-suite clients but should
not be used as a frequent polling endpoint. Configuration output contains no
Wi-Fi/MQTT passwords, private keys, certificate payloads or password verifiers.
USB diagnostics distinguish `usb_device`, `usb_ncm_hardware`,
`usb_ncm_runtime` and `usb_ncm_available`; clients must use the last value for
effective availability rather than inferring support from the runtime symbol.
Alpha 6 reports each release-qualification gate as a bounded name/status pair;
full measurements remain in the on-device Maintenance view and qualification
evidence file rather than expanding routine API polling payloads.
