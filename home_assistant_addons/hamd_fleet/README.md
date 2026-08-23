# HAMD Fleet Manager add-on

This v2 alpha add-on provides an ingress dashboard, persistent device
inventory, bounded event retention, mTLS polling, independently signed fleet
policies, maintenance windows, ordered rollout cohorts, automatic failure-stop
thresholds and bounded update/rollback commands. Inventory, events, rollout
state, and idempotent background jobs are transactionally stored in SQLite;
queued work survives add-on restarts and retries with bounded backoff.

Copy the fleet mTLS client certificate, key and issuing CA into Home Assistant's
`/ssl` directory, install the add-on repository, start **HAMD Fleet Manager**,
then register the device hostname and certificate paths in the ingress UI.

On first start the add-on creates `/data/fleet-signing-key.pem` and exposes the
raw public half at **Fleet verification key**. Provision that 64-byte public key
as `.fleet-verification-key` on the test device. The key is not the HAMD update
signing key and must be backed up independently.

The add-on has no host port mapping. Management UI access is through
authenticated Home Assistant ingress and is restricted to Home Assistant
administrators by the add-on manifest.

For a staged release, assign devices to cohorts such as `canary` and `main`,
create a rollout with those cohorts in order, then dispatch the active cohort.
Record each device result after its trial/health observation. The add-on will
not advance while a result is missing or failed and stops the rollout once the
configured absolute failure threshold is reached.
