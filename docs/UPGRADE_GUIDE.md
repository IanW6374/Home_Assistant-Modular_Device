# IoT-MD v2 upgrade and recovery guide

## Artifact types

- `.iotapp`: application and selected drivers.
- `.iotcore`: secure MicroPython core firmware.
- `.iotuni`: matched application and core for one coordinated upgrade.
- `.factory.bin`: device seeding and USB disaster recovery only.

Every deployable artifact is signed with ECDSA P-256/SHA-256, identifies its
source revision and carries a monotonically increasing release sequence.

## Portal upgrade

### Transition from v2.0.x

The v2.1 formats and encrypted configuration namespace are intentionally a clean
break. Do not use a universal container while crossing this boundary. On the
existing v2.0.13 test device, install and restart after every component:

1. `application-2.0.15.hamd`
2. `ham-core-2.0.15.hamf`
3. `ham-core-2.0.16.hamf`
4. `application-2.1.1.iotapp`
5. `iotmd-core-2.1.1.iotcore`

If the device already reports application v2.0.15 and core v2.0.16, begin at
step 4. The transition application copies and byte-verifies the encrypted
configuration while retaining the v2.0 namespace for rollback. v2.0.16 allows
the frozen recovery supervisor to validate and boot the `iotmd.py` entry point.

1. Back up the current configuration.
2. Open **Maintenance > Upgrades**.
3. Upload the artifact and wait for upload, verification and staging to finish.
4. Review the staged type and version.
5. Activate and reboot.
6. Wait for trial health confirmation and verify the running application/core
   versions on the overview page.

All three upload types are resumable. Retrying the same `.iotapp`, `.iotcore` or
`.iotuni` continues from its last committed 64 KiB chunk; selecting a different
artifact discards the interrupted upload and reclaims its storage. The portal
rejects an artifact before accepting bytes when the complete upload cannot fit
with the required storage reserve.

Universal format 3 does not store the combined container on the device. The
browser submits its small signed outer manifest first; the device then accepts
the exact signed core and application bundles sequentially. The core is written
and read-back verified in the inactive OTA partition before the application is
adopted in place. Only after both required components match the signed outer
version, release sequence, size and SHA-256 values does the device expose paired
activation. The persistent plan and normal resumable offsets survive a browser
refresh or interrupted connection.

The one-time transition from a core/application that predates sequential
transport requires the new `.iotapp` first. Restart and confirm that application,
then upload the matching `.iotuni`; the portal skips the already-installed
application and stages the core from the universal container. Once that core is
confirmed, later format-3 `.iotuni` releases can upgrade both components directly.

Do not interrupt power during core activation. A rejected or failed artifact
must remain visibly failed in the portal; consult the structured log for its
reason.

### Automatic release checks

**Maintenance > Upgrades > Automatic upgrade** separates an immediate manual
check from saved scheduling preferences. A schedule can be disabled, daily at
the selected device-local time, or weekly at the selected weekday and local
time. The device time zone is configured under **System > Time / Date**.

**Automatically download applicable signed releases** and **Automatically
activate verified releases** are independent settings. A check without
automatic download only reports availability; a download without automatic
activation leaves the verified release staged for an administrator. Fleet
policy can additionally prevent automatic activation while a rollout is paused
or outside its maintenance window. Manual uploads remain available regardless
of the automatic check schedule.

## Production build

Build only from a clean, tested commit. This example uses production version
`2.3.1` and release sequence `2501`:

```sh
python3 tools/build_update.py releases/v2.3.1/application-2.3.1.iotapp \
  --version 2.3.1 --release-sequence 2501 \
  --signing-key /secure/update.signing-key \
  --mpy-cross /path/to/micropython/mpy-cross/build/mpy-cross

python3 tools/build_micropython_firmware.py \
  --micropython-root /path/to/micropython \
  --version 2.3.1 --release-sequence 2501 \
  --output releases/v2.3.1/iotmd-core-2.3.1.iotcore \
  --factory-output /secure-output/iotmd-core-2.3.1.factory.bin \
  --signing-key /secure/update.signing-key --production-security \
  --secure-boot-signing-key /secure/secure-boot-signing-key.pem \
  --factory-setup-password-output /secure-output/device-v2.1.setup-password.txt

python3 tools/build_universal_update.py \
  releases/v2.3.1/universal-2.3.1.iotuni \
  --application releases/v2.3.1/application-2.3.1.iotapp \
  --firmware releases/v2.3.1/iotmd-core-2.3.1.iotcore \
  --version 2.3.1 --release-sequence 2501 \
  --signing-key /secure/update.signing-key
```

Production application bundles compile importable modules to `.mpy` bytecode.
The entry point and source-provenance module remain readable Python. The
universal builder enforces a 1.5 MiB limit on each sequential component rather
than claiming that an arbitrary combined size is safe on a populated filesystem.

Generate SBOM and provenance with `tools/generate_sbom.py` and
`tools/generate_provenance.py`. Store private keys and setup-password outputs
outside any public release site.

## Clean USB reseed

A reseed erases application state, settings, credentials, certificates and
logs. Use the exact serial device and acknowledge erasure explicitly:

```sh
python3 tools/reseed_device_usb.py \
  --device /dev/cu.usbmodemXXXX \
  --bundle releases/v2.2.9/iotmd-core-2.2.9.iotcore \
  --application-bundle releases/v2.2.9/application-2.2.9.iotapp \
  --micropython-root /path/to/micropython \
  --setup-password-file /secure-output/device-v2.1.setup-password.txt \
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

Release-specific reports are indexed in
[`docs/qualification`](qualification/README.md).
