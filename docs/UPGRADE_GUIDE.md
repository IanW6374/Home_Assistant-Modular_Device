# HAMD v2 upgrade and recovery guide

## Artifact types

- `.hamd`: application and selected drivers.
- `.hamf`: secure MicroPython core firmware.
- `.hamu`: matched application and core for one coordinated upgrade.
- `.factory.bin`: device seeding and USB disaster recovery only.

Every deployable artifact is signed with ECDSA P-256/SHA-256, identifies its
source revision and carries a monotonically increasing release sequence.

## Portal upgrade

1. Back up the current configuration.
2. Open **Maintenance > Upgrades**.
3. Upload the artifact and wait for upload, verification and staging to finish.
4. Review the staged type and version.
5. Activate and reboot.
6. Wait for trial health confirmation and verify the running application/core
   versions on the overview page.

Application and core-only uploads are resumable. Retrying the same `.hamd` or
`.hamf` continues from its committed offset; selecting a different artifact
discards the interrupted upload and reclaims its storage. The portal rejects an
artifact before accepting bytes when the complete upload cannot fit with the
required storage reserve.

Universal `.hamu` bundles are streamed directly into the core and application
installers rather than cached on the device filesystem. Keep the browser and
device connected until upload and verification finish; an interrupted
universal upload can be safely restarted from the beginning.

Do not interrupt power during core activation. A rejected or failed artifact
must remain visibly failed in the portal; consult the structured log for its
reason.

## Production build

Build only from a clean, tested commit. This example uses production version
`2.0.0` and release sequence `2200`:

```sh
python3 tools/build_update.py releases/v2.0.0/application-2.0.0.hamd \
  --version 2.0.0 --release-sequence 2200 \
  --signing-key /secure/update.signing-key

python3 tools/build_micropython_firmware.py \
  --micropython-root /path/to/micropython \
  --version 2.0.0 --release-sequence 2200 \
  --output releases/v2.0.0/ham-core-2.0.0.hamf \
  --factory-output releases/v2.0.0/ham-core-2.0.0.factory.bin \
  --signing-key /secure/update.signing-key --production-security \
  --secure-boot-signing-key /secure/secure-boot-signing-key.pem \
  --factory-setup-password-output releases/v2.0.0/device-v2.setup-password.txt

python3 tools/build_universal_update.py \
  releases/v2.0.0/universal-2.0.0.hamu \
  --application releases/v2.0.0/application-2.0.0.hamd \
  --firmware releases/v2.0.0/ham-core-2.0.0.hamf \
  --version 2.0.0 --release-sequence 2200 \
  --signing-key /secure/update.signing-key
```

Generate SBOM and provenance with `tools/generate_sbom.py` and
`tools/generate_provenance.py`. Store private keys and setup-password outputs
outside any public release site.

## Clean USB reseed

A reseed erases application state, settings, credentials, certificates and
logs. Use the exact serial device and acknowledge erasure explicitly:

```sh
python3 tools/reseed_device_usb.py \
  --device /dev/cu.usbmodemXXXX \
  --bundle releases/v2.0.0/ham-core-2.0.0.hamf \
  --application-bundle releases/v2.0.0/application-2.0.0.hamd \
  --micropython-root /path/to/micropython \
  --setup-password-file releases/v2.0.0/device-v2.setup-password.txt \
  --update-signing-key /secure/update.signing-key \
  --confirm-erase-user-state
```

After reseeding, complete first-boot setup and restore a validated encrypted
backup if required.

## Qualification

Before publication, run all repository checks and execute:

```sh
python3 tools/hil_qualify.py --host device.local \
  --ca ca.pem --cert client.pem --key client-key.pem \
  --output qualification.json
```

Also verify first boot, portal/API TLS, MQTT, interrupted upload, low-storage
cleanup, universal activation, watchdog recovery, rollback and configuration
restore on production-equivalent hardware.
