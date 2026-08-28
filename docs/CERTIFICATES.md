# Certificate identities and provisioning

IoT-MD deliberately separates browser-facing and service-facing trust.

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

The first-boot wizard starts with a certificate-route selector and displays
only the fields for the selected route:

1. **Automatic IoT CA enrollment** obtains a browser-trusted portal
   certificate and a private-CA Device API identity through a short-lived,
   trusted-LAN enrollment window.
2. **IoT CA enrollment file (`.iotenroll`)** obtains the same identity
   set from a one-time, host-bound authorization downloaded by the admin.
3. **Private CA ACME enrollment** uses the device's `.local` name and HTTP-01 against
   the private IoT CA.
4. **Manual certificate package** uploads an existing public portal chain/key
   and private Device API certificate/key.
5. **Self-signed certificate** keeps the device-generated local fallback.

No route is silently applied. Selecting **Self-signed certificate** requires no
certificate fields and continues with the identity created during the network
step.

### Renewal coverage

Renewal depends on the selected route and is shown beside every choice in the
wizard:

- **Private CA ACME enrollment** automatically renews its local portal certificate
  after two-thirds of its lifetime. It does not install or rotate a separate
  Device API identity.
- **Automatic IoT CA enrollment** and **IoT CA enrollment file (`.iotenroll`)**
  install the public portal, private Device API and renewal identities together.
  The device uses the renewal identity to rotate the complete set automatically
  after two-thirds of either server certificate lifetime.
- **Manual certificate package** certificates are replaced manually; neither the public nor
  private identity is auto-renewed.
- **Self-signed certificate** mode regenerates its local identity automatically
  after two-thirds of its lifetime.

## Automatic IoT CA enrollment

For one-step provisioning, configure IoT CA with a server name the device can
resolve (by default `iot-ca.home.arpa`) and ensure its Home Assistant network
mapping matches the configured provisioning port (9010 by default). Open the
automatic IoT-MD enrollment window from the CA Overview; it closes after the
configured interval, five minutes by default. In the device wizard, leave the
server and port blank to use those defaults or enter the matching values, then
choose **Request and install certificates**. The CA accepts only private-LAN
requests, rate-limits them, audits each authorization and derives both
identities from the device's `<host>.local` name.

The private-CA ACME route similarly treats a blank directory URL as
`https://iot-ca.home.arpa:9000/acme/acme/directory`. If the CA/ACME port is
remapped from 9000 in Home Assistant, enter the corresponding URL instead.

The first automatic exchange is a trusted-LAN bootstrap because the device
does not yet possess the private root. The returned authorization pins all
subsequent enrollment traffic to that root. On an untrusted setup LAN, choose
**Authorize IoT-MD** in IoT CA, enter the portal host label and download the
resulting `.iotenroll` file instead. That authorization expires after 30
minutes and can be claimed only once with the same certificate requests.

Select **IoT CA enrollment file (`.iotenroll`)** and upload that one
file. The device pins HTTPS to the private root embedded in the file,
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

Issue an **IoT-MD public portal** profile in IoT Certificate Authority before
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
