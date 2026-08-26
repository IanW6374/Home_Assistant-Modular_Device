# Certificate identities and provisioning

IoTMD deliberately separates browser-facing and service-facing trust.

| Purpose | Identity or trust | Expected issuer |
| --- | --- | --- |
| Web portal HTTPS | `web.crt.pem` / `web.key.der` | Public ACME for the configured portal DNS name |
| Device API and fleet server | `api-server.crt.der` / `api-server.key.der` | Private IoT CA for the device `.local` name |
| MQTT server authentication | `mqtt-ca.der` | Private CA used by the broker |
| Release server authentication | `update-ca.der` | Private CA used by the release service |
| Syslog server authentication | Dedicated Syslog trusted CA | Private CA used by IoT Syslog |
| API/fleet clients | One or more API client CAs and enrolled client certificates | Private IoT CA |

The public certificate is limited to the human-facing portal. MQTT, Device API,
fleet, Syslog and release services do not become public merely because the
portal has a browser-trusted certificate.

## Initial setup

Issue an **IoT MD public portal** profile in IoT Certificate Authority before
starting device provisioning. The CA performs Cloudflare DNS-01 and returns a
one-time ZIP. Unzip it on the administrator workstation; do not copy the ZIP or
Cloudflare credentials to the device.

On the first-boot **Install device certificates** page, select:

1. the private IoT root as **Home IoT trusted CA**;
2. the public portal DNS hostname;
3. `web.crt.pem` (leaf plus intermediate chain) and `web.key.der` for the public portal;
4. `api-server.crt.der` and `api-server.key.der` for private API/fleet service.

The device validates both key pairs before committing the certificate set. Its
`.local` mDNS hostname remains separate from the public portal DNS name, so API
clients can continue to use private name resolution and private CA validation.

The first-boot wizard installs an already-issued profile package. It does not
contact Cloudflare or store a Cloudflare token. This is intentional: an
unprovisioned field device must not receive DNS-edit authority.

## Upgrades from 2.1.1

When the independent Device API identity files are absent, the first boot after
upgrade copies the existing portal identity once so that the API remains
reachable. The Certificates page marks this as an upgrade identity. Install a
private-CA Device API server certificate and key to clear the warning. Future
portal certificate changes never update the API identity.

Complete encrypted backups include both identities. Restore validates each
certificate/key pair before activation.
