# IoT-MD management ecosystem

The device project has one IoT-MD-specific management add-on and two generic
security/logging add-ons. They intentionally remain independently installable.

## IoT-MD Management Suite

The public `HA-IoT-MD-Management-Suite` Home Assistant add-on combines:

- device enrollment, inventory, health and event history;
- signed fleet policy and queued command coordination;
- staged rollouts and device result tracking;
- synchronization and verification of tagged GitHub Release assets;
- a verified release inventory with explicit Stable/Beta promotion;
- a TLS release endpoint for `.iotapp`, `.iotcore` and `.iotuni` artifacts;
- Home Assistant Ingress for the management UI and release administration.

Release files live in persistent add-on storage. Before import, the suite uses
the pinned offline update public key to verify bundle signatures and payload
hashes, GitHub asset digests, SLSA provenance and SBOM presence. It never
contains the offline IoT-MD update-signing private key. HTTPS uses the
certificate/key configured from Home Assistant's `/ssl` share. Devices
authenticate the release server with the installed Release trusted CA.

Promotion creates a format-3 channel catalog signed by the same Management
Suite identity used for fleet policy. Download its public key from the suite and
import it on each device under **Maintenance > Certificates > Management Suite
verification key**. A device verifies fleet policy and the catalog with this
key and still verifies the downloaded `.iotapp` or `.iotcore` bundle with its
immutable update key. Compromise of the suite can therefore select an already
signed artifact, but cannot create a new trusted artifact or bypass
release-sequence rollback protection.

## Generic companion add-ons

- **IoT Certificate Authority** issues and renews certificates for IoT-MD and
  unrelated services. It remains a separate trust boundary and repository.
- **IoT Syslog** receives encrypted RFC 5425/5424-style device and audit
  events, provides search/filtering and applies administrator-defined retention.

Keeping these generic avoids forcing CA or logging users to install fleet and
release functions. Home Assistant supports multiple certificate and key files
in `/ssl`; each add-on is configured with explicit filenames rather than a
single global certificate.

## Trust flow

```text
IoT Certificate Authority -> server/client certificates -> /ssl and devices
offline IoT-MD signing key  -> signed release artifacts -> Management Suite
Management Suite key         -> fleet policy + Stable/Beta index -> IoT-MD devices
IoT-MD devices              -> TLS syslog events        -> IoT Syslog
Management Suite           <-> mTLS fleet API          <-> IoT-MD devices
```

TLS proves the service or client identity. Artifact signatures independently
prove that a release was authorized and enforce the monotonic release sequence.
