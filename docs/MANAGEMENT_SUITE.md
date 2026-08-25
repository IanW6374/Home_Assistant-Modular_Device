# IoTMD management ecosystem

The device project has one IoTMD-specific management add-on and two generic
security/logging add-ons. They intentionally remain independently installable.

## IoTMD Management Suite

The public `IoTMD-Management-Suite` Home Assistant add-on combines:

- device enrollment, inventory, health and event history;
- signed fleet policy and queued command coordination;
- staged rollouts and device result tracking;
- a TLS release endpoint for `.iotapp`, `.iotcore` and `.iotuni` artifacts;
- Home Assistant Ingress for the management UI and release administration.

Release files live in persistent add-on storage. The server distributes signed
artifacts but never contains the offline IoTMD update-signing private key. HTTPS
uses the certificate/key configured from Home Assistant's `/ssl` share. Devices
authenticate the release server with the installed Release trusted CA.

## Generic companion add-ons

- **IoT Certificate Authority** issues and renews certificates for IoTMD and
  unrelated services. It remains a separate trust boundary and repository.
- **IoT Syslog Server** receives encrypted RFC 5425/5424-style device and audit
  events, provides search/filtering and applies administrator-defined retention.

Keeping these generic avoids forcing CA or logging users to install fleet and
release functions. Home Assistant supports multiple certificate and key files
in `/ssl`; each add-on is configured with explicit filenames rather than a
single global certificate.

## Trust flow

```text
IoT Certificate Authority -> server/client certificates -> /ssl and devices
offline IoTMD signing key  -> signed release artifacts -> Management Suite
IoTMD devices              -> TLS syslog events        -> IoT Syslog Server
Management Suite           <-> mTLS fleet API          <-> IoTMD devices
```

TLS proves the service or client identity. Artifact signatures independently
prove that a release was authorized and enforce the monotonic release sequence.
