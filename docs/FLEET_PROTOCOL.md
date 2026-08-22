# HAMD fleet protocol v1

## Transport and identity

The Home Assistant add-on connects to `/api/v2` over HTTPS with mandatory
mutual TLS. A client certificate is enrolled with `fleet:read` and, when
remote management is wanted, `fleet:write` scopes. Device identity is the
factory device identifier plus the certificate fingerprint; editable hostnames
are display attributes only.

Fleet policies use a dedicated P-256 trust domain. The add-on holds the fleet
policy private key in protected add-on storage and each managed device holds
only `.fleet-verification-key`. This key is independent of the offline release
signing and Secure Boot keys. `tools/generate_fleet_signing_key.py` creates the
initial pair; the public half is provisioned during device enrolment.

## Inventory document

Inventory contains product, application, core and MicroPython versions;
release sequences; board; capabilities; configured driver metadata; network
quality; update state; clock quality; and an event cursor. Secrets, private
keys, password verifiers and Wi-Fi credentials are never returned.

## Signed policy

A policy is accepted only when its ECDSA P-256 signature is valid, its sequence
is newer than the stored sequence, its device/cohort target matches, and its
validity period can be evaluated with a synchronised clock.

Format 1 fields are:

- `format_version`, `target_board`, `policy_sequence`, `issued_at`, `not_before`, `expires_at`
- `target_device`, `target_cohort`
- `maintenance`: allowed weekdays, local start minute and duration
- `updates`: channel, automatic download, automatic activation and maximum
  consecutive failures
- `telemetry`: enabled, minimum interval and event severities
- `commands`: bounded requested actions, each with a unique identifier
- `signature_scheme`, `signature`

Policies never carry credentials or arbitrary code. Unknown fields are
rejected in alpha so misspellings cannot silently weaken a control.

## Rollout model

The add-on assigns a release to ordered cohorts. It advances only after the
current cohort has remained healthy for its observation interval. A configured
absolute or percentage failure threshold pauses the rollout. Rollback is a
separate signed request referencing the release and the last confirmed slot.

## Event synchronisation

Events are fetched using a monotonically increasing cursor. Devices retain a
bounded local window; the add-on provides longer retention. A cursor gap is
reported explicitly so absence of records is not confused with absence of
events.
