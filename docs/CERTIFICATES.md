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

## Initial setup choices

The administrator explicitly selects one of four certificate routes in the
first-boot wizard:

1. **IoT CA public certificate provisioning** obtains a browser-trusted portal
   certificate and a private-CA Device API identity using an automatic,
   short-lived enrollment window or a one-time `.iotenroll` authorization.
2. **Local private-CA ACME** uses the device's `.local` name and HTTP-01 against
   the private IoT CA.
3. **Manual certificate package** uploads an existing public portal chain/key
   and private Device API certificate/key.
4. **Self-signed certificate** keeps the device-generated local fallback.

No route is silently selected. The self-signed identity created during the
network step remains active unless the administrator completes another route.

## Automated IoT CA public provisioning

For one-step provisioning, configure IoT CA with a server name the device can
resolve (normally `homeassistant.local`), restart the add-on if that name has
changed, then enable automatic IoT MD enrollment. The window closes after 15
minutes. In the device wizard, confirm the same server name and choose
**Request and install certificates**. The CA accepts only private-LAN requests,
rate-limits them, audits each authorization and derives both identities from
the device's `<host>.local` name.

The first automatic exchange is a trusted-LAN bootstrap because the device
does not yet possess the private root. The returned authorization pins all
subsequent enrollment traffic to that root. On an untrusted setup LAN, choose
**Authorize IoT MD** in IoT CA, enter the portal host label and download the
resulting `.iotenroll` file instead. That authorization expires after 30
minutes and can be claimed only once with the same certificate requests.

Upload that one file under the authorization-file fallback in **IoT CA
automatic provisioning**. The device pins HTTPS to the private root embedded in the file,
generates independent P-256 keys for the portal, Device API and renewal
identity, and submits only their CSRs. IoT CA completes Cloudflare DNS-01 for
the portal CSR and signs the API and renewal CSRs with its private authority.
The returned response contains certificates and public trust only. It never
contains a private key or Cloudflare token.

The Device API server identity is installed as a leaf-plus-intermediate PEM
chain (the filename remains the established API certificate path), allowing
clients that trust the private root to validate the complete chain.

The device checks that the authorization's `.local` API hostname matches the
name selected earlier in setup, verifies each certificate/key pair, and
commits the complete set with rollback protection.

## Manual public profile provisioning

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

The manual route installs an already-issued profile package. The automated
route contacts IoT CA, not Cloudflare, and neither route stores a Cloudflare
token on the device. An unprovisioned field device never receives DNS-edit
authority.

## Upgrades from 2.1.1

When the independent Device API identity files are absent, the first boot after
upgrade copies the existing portal identity once so that the API remains
reachable. The Certificates page marks this as an upgrade identity. Install a
private-CA Device API server certificate and key to clear the warning. Future
portal certificate changes never update the API identity.

Complete encrypted backups include both identities. Restore validates each
certificate/key pair before activation.
