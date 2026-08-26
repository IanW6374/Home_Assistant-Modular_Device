# Device API v2

The Device API is a JSON HTTPS interface for inventory, state, diagnostics,
commands, events, support data and fleet coordination. It listens on port 8444
by default and always requires mutual TLS. The machine-readable contract is
[`openapi.yaml`](openapi.yaml).

Its server certificate is stored independently from the web portal identity
and is expected to chain to the private IoT CA. A public portal renewal never
changes the Device API/fleet server identity.

## Authentication and authorization

Install one or more API client CAs under **Maintenance > Certificates**, then
enable the listener under **System > Device API**. Each client certificate is
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
| GET | `/api/v2/device/inventory` | `read` | Device, module and fleet inventory |
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
curl --cert client.crt --key client.key --cacert device-ca.crt \
  https://iotmd01.local:8444/api/v2/modules/00A1/state
```

```json
{"module":"00A1","state":{"temperature":21.7,"humidity":48}}
```

Routine GETs increment aggregate counters but are logged only at debug level;
mutating calls create health and audit records. Responses are `no-store` JSON.
Typical failures are `400` malformed input, `401` missing/invalid identity,
`403` insufficient scope, `404` unknown endpoint/module/operation, `413`
oversized input and `503` temporarily unavailable service.
