# ESP32-S3 installation and upgrade guide

This guide applies to the supported ESP32-S3-DevKitC-1-N8R8 target. The
current build is pinned by `firmware/build-lock.json` to:

| Component | Required value |
| --- | --- |
| MicroPython | `v1.28.0` at `e0e9fbb17ed6fd06bb76e266ae554784c9c80804` |
| ESP-IDF | `v5.5.1` at `fcae32885b0296b32044cb99ecbdc50d98dddb83` |
| Project board | `HAM_ESP32_S3` |
| Board variant | `SPIRAM_OCT` |
| Flash/PSRAM | 8 MB / 8 MB Octal |
| OTA application slots | `ota_0` and `ota_1`, 2 MiB each |
| Frozen recovery API | `6` |
| Frozen core API | `8` |

## Host Python and MicroPython are different

Commands beginning with `python3`, `python`, or `mpremote` run on the Mac or
other development computer. They build packages, invoke ESP-IDF, or transfer
files. They do not run the device application under CPython.

Files in the project root, `device_modules/`, and `lib/` run under
MicroPython on the ESP32-S3. Validate those files with the `mpy-cross` binary
from the pinned MicroPython checkout. Use CPython's `py_compile` only for
host-only `tools/` and `tests/`. MicroPython supports constructs and modules
that CPython does not, so a CPython syntax/import failure is not automatically
a device-code defect.

Set reusable host variables before following a procedure. Replace each example
path and serial port with the value on the build computer:

```sh
export HAM_PROJECT_ROOT=/path/to/Home_Assistant-Modular_Device
export MICROPYTHON_ROOT=/path/to/micropython
export IDF_ROOT=/path/to/esp-idf
export DEVICE_PORT=/dev/cu.usbmodem1101
export UPDATE_SIGNING_KEY="$HOME/.ham-device/update.private-key"
export SECURE_BOOT_KEY="$HOME/.ham-device/secure_boot_signing_key.pem"
cd "$HAM_PROJECT_ROOT"
```

Release sequences, not display labels, are the anti-rollback authority. Never
reuse a confirmed sequence for a different build. Application and core bundles
for one product release should share the same HAMD version label; MicroPython is
reported separately.

When both bundles are published in one signed channel descriptor, the device
treats them as a persistent paired update. It stages and activates core firmware
first, confirms the firmware trial at the normal health boundary, then resumes
the application download automatically after reboot. The portal reports
**Firmware step 1 of 2** and **Application step 2 of 2**. Do not remove either
bundle from the channel until devices have had enough time to complete both
steps.

## Before any remote update

1. Confirm the portal shows the expected **Application**, **Core firmware**,
   **MicroPython version**, **Update status: idle**, and **OTA firmware
   availability: ready**.
2. Keep the device powered throughout upload, verification, activation, and
   reboot.
3. Open the portal URL (or the custom port selected in Portal Settings):

   ```text
   https://<device-ip>:8443/
   ```

   HTTPS is selected by default when a certificate is installed. Explicit HTTP
   mode uses port `8080` by default and is intended only for trusted networks.
   Sign in with the username and password chosen in the first-boot wizard; the
   portal retains authentication in an HttpOnly, SameSite session cookie
   (`Secure` is added for HTTPS).
4. Keep the HTTPS certificate/key current and trusted by the operator.
5. Confirm update features are enabled in signed `app_settings.json`; maximum
   bundle sizes and protected-update permission are defined by frozen
   `device_config.py`:

   ```json
   {
     "web_portal": {
       "enabled": true,
       "updates_enabled": true,
       "firmware_updates_enabled": true
     }
   }
   ```

Protected certificate maintenance is permitted by the frozen device policy but
still requires an explicit certificate selection at activation. Credentials
and user settings in encrypted NVS are never update content.

## Update signing

Signing is mandatory. The device stores only `/.update-verification-key`; both
unsigned bundles and legacy HMAC bundles are rejected.

`UPDATE_SIGNING_KEY` contains the path to the private host key file; it does not
contain the key itself. The `--signing-key "$UPDATE_SIGNING_KEY"` option used by
the application and firmware builders reads this existing file—it does not
generate a key.

Generate the ECDSA P-256 private key once on the signing computer:

```sh
cd "$HAM_PROJECT_ROOT"
export UPDATE_SIGNING_KEY="$HOME/.ham-device/update.private-key"

python3 tools/provision_update_signing.py \
  --private-key "$UPDATE_SIGNING_KEY" \
  --generate
```

The helper refuses to overwrite an existing key. Do not delete or regenerate
the key after provisioning devices: bundles signed with a replacement key will
be rejected by devices that still hold the original. Keep the key outside the
repository, and store a secure backup. Every
device intended to accept the same release bundles must receive the derived
public key. The private key must never be copied to a device.

Validate an existing host key without changing it:

```sh
python3 tools/provision_update_signing.py \
  --private-key "$UPDATE_SIGNING_KEY"
```

For a mounted VFS, provision it with:

```sh
python3 tools/provision_update_signing.py \
  --private-key "$UPDATE_SIGNING_KEY" \
  --mount /path/to/device-vfs
```

For a serial-only device, first write the public key on the host, then copy it:

```sh
python3 tools/provision_update_signing.py \
  --private-key "$UPDATE_SIGNING_KEY" \
  --public-key-output /tmp/update-verification-key
mpremote connect "$DEVICE_PORT" fs cp \
  /tmp/update-verification-key :.update-verification-key
```

This copies only the public key. Provisioning is performed over USB before
remote updates.

New factory images derive the public key and embed it in encrypted NVS. The
private key remains on the signing host. Settings and certificates are shared
VFS files outside application slots; encrypted credentials are neither VFS
update content nor application-slot content.

Signing helper options:

| Option | Required | Meaning |
| --- | --- | --- |
| `--private-key PATH` | Yes | Offline host P-256 private-key file. |
| `--generate` | No | Create a new key; refuses to overwrite an existing key. |
| `--mount PATH` | No | Copy only the public key to `.update-verification-key` on a mounted VFS. |
| `--public-key-output PATH` | No | Write the derived public key for serial provisioning. |
| `-h`, `--help` | No | Show the current command syntax. |

## 1. Application upgrade (`.hamd`)

Use an application upgrade for routine changes to `HA-Device.py`, the web
portal, settings loader, display code, selected drivers, and selected libraries.
It uses transactional A/B Python application slots.

`main.py` is the permanent minimal launcher. The recovery/update/security
modules are frozen into MicroPython and are intentionally excluded from
`.hamd`; update those components with a core `.hamf` upgrade.

### Step 1: choose a version and build

For a normal code-only update using the repository's active configuration:

```sh
cd "$HAM_PROJECT_ROOT"
python3 tools/build_update.py \
  application-1.5.0.hamd \
  --version 1.5.0 \
  --release-sequence 1500 \
  --signing-key "$UPDATE_SIGNING_KEY"
```

The builder creates the profile-free universal runtime and includes every
production driver. The installed module configuration controls which drivers
are imported.

For a code-only fleet update, omit settings; each device lazily imports only
the drivers named by its own configuration:

```sh
python3 tools/build_update.py \
  application-1.5.0-universal.hamd \
  --version 1.5.0 \
  --release-sequence 1500 \
  --signing-key "$UPDATE_SIGNING_KEY"
```

There are no device profiles. Signed runtime and driver component versions let
a device skip a release that changes only an unconfigured module.

To include the active settings as optional activation choices:

```sh
python3 tools/build_update.py \
  application-1.5.0-with-settings.hamd \
  --version 1.5.0 \
  --release-sequence 1500 \
  --include-module-settings \
  --signing-key "$UPDATE_SIGNING_KEY"
```

To build for non-default settings files:

```sh
python3 tools/build_update.py \
  application-1.5.0-ems.hamd \
  --version 1.5.0 \
  --release-sequence 1501 \
  --module-settings examples/module_settings.ems.json \
  --signing-key "$UPDATE_SIGNING_KEY"
```

Module settings are the only optional settings activation group. If no module
file is installed, the device starts with zero modules and exposes the
dedicated **Modules** editor/uploader. Signed `app_settings.json` is mandatory
application content; user settings remain in encrypted NVS.

To build a protected maintenance bundle:

```sh
python3 tools/build_update.py \
  credentials-2026-07.hamd \
  --version credentials-2026-07 \
  --release-sequence 202607 \
  --protected-only \
  --certificate trust/home-iot-root.der=home-iot-root.der \
  --certificate web.crt.der \
  --certificate web.key.der \
  --signing-key "$UPDATE_SIGNING_KEY"
```

### Application builder options

| Argument | Required | Meaning |
| --- | --- | --- |
| `output` | Yes | Positional output path; use a `.hamd` suffix. |
| `--version LABEL` | Yes | HAMD application or maintenance version label. |
| `--release-sequence N` | Yes | Positive signed sequence; must be greater than the confirmed application sequence on every target device. |
| `--include-protected` | No | Include explicitly selected certificates. Requires protected-update permission when activated. |
| `--protected-only` | No | Exclude application files and build only certificate maintenance content. |
| `--include-module-settings` | No | Include the default `module_settings.json` as an optional overwrite. |
| `--module-settings PATH` | No | Analyse this non-default module settings file and package it as `module_settings.json`. |
| `--certificate PATH` or `--certificate TARGET=PATH` | No | Add a certificate/key under `certs/`. `TARGET` supports a safe relative path such as `trust/home-iot-root.der`. Repeat once per file. Supplying it makes the bundle protected. |
| `--signing-key PATH` | Yes | Sign with the offline ECDSA P-256 private key. |
| `-h`, `--help` | No | Show the current command syntax. |

### Step 2: upload and verify

1. Open **Maintenance > Upgrades** in the authenticated portal.
2. Select the `.hamd` file with the single update chooser.
3. Select **Upload and verify**.
4. Wait for **Uploading** to reach 100%, then for **Verifying** to reach 100%.
   Do not manually refresh while an upload is active. Normal portal refresh is
   paused automatically.
5. Confirm **Staged version** shows the application label and **Update status**
   is `ready`.

### Step 3: choose optional shared files

The portal shows switches only for optional groups present in the bundle:

- **Module settings** installs `module_settings.json`.
- **Certificates** installs selected files under `/certs`.

Application/runtime files are always applied. Optional switches default off.
Select only the shared files intended for this device.

### Step 4: activate and verify health

1. Select **Activate and reboot** once.
2. Leave the device powered and do not interrupt its serial REPL during the
   trial. The inactive application slot is prepared and the module reboots.
3. Allow up to three minutes for local startup plus Wi-Fi and authenticated
   portal health confirmation. MQTT connectivity is checked separately.
4. Reopen the portal and sign in if its previous session was lost.
5. Confirm the new **Application** version, **Update status: idle**, a non-legacy
   **Active slot**, and expected module health/MQTT state.

If activation is interrupted, the next boot removes the unconfirmed slot and
restores backed-up shared files. The portal update history records staged,
trial, confirmed, rejected, activation-failed, and rollback events.

### Remote stable and beta hosting

Publish a verified bundle and its signed descriptor into a static HTTPS tree:

```sh
python3 tools/publish_release.py \
  --bundle application-1.5.0-universal.hamd \
  --output-root release-site \
  --base-url https://updates.example/hamd \
  --channel stable \
  --notes "Universal HAMD runtime 1.5.0" \
  --signing-key "$UPDATE_SIGNING_KEY"
```

Upload `release-site/` without changing its layout. Configure devices with
`https://updates.example/hamd/{channel}/latest.json`. Publish both application
and firmware bundles to the same output root. The publisher stores both under
`bundles/` and writes one `stable/latest.json` or `beta/latest.json` containing
their independently signed descriptors. The device filters entries by its
installed recovery/core API, selects a needed compatible firmware release
first, then selects an applicable application release without requiring the
server operator to replace the descriptor.

Opening **Maintenance > Upgrades** shows the last automatic-check result and
does not initiate network activity. Automatic checks are disabled by default;
select a daily or weekly schedule, local time, and (for weekly checks) day on
that page. **Check for updates** remains available for an explicit retry. The
verified descriptor and notes are shown before **Download and verify** streams it to the inactive
application slot or firmware partition. HTTPS redirects and chunked transfer
are supported. The device rejects an incompatible core/configuration API, a
changed size or hash,
a descriptor/bundle sequence mismatch, or a sequence that is not newer than
the installed release. Automatic download and activation are separate opt-ins;
keep automatic activation disabled until fleet rollback behaviour is proven.

## 2. Core MicroPython upgrade (`.hamf`)

Use a core upgrade for MicroPython itself or any frozen module:
`recovery_boot.py`, `app_update.py`, `firmware_update.py`,
`hardware_platform.py`, `update_security.py`, `update_support.py`, or
`wifi_recovery.py`.

### Step 1: activate the pinned ESP-IDF

```sh
source "$IDF_ROOT/export.sh"
idf.py --version
```

The version output must contain `5.5.1`. If `idf.py` is not found, the export
script was not sourced from the actual ESP-IDF installation used for the build.

### Step 2: build and package in one command

```sh
cd "$HAM_PROJECT_ROOT"
python3 tools/build_micropython_firmware.py \
  --micropython-root "$MICROPYTHON_ROOT" \
  --version 1.5.0 \
  --release-sequence 1500 \
  --output releases/release-site-1.5.0/bundles/ham-core-1.5.0.hamf \
  --factory-output releases/factory-artifacts/ham-core-1.5.0.factory.bin \
  --signing-key "$UPDATE_SIGNING_KEY" \
  --production-security \
  --secure-boot-signing-key "$SECURE_BOOT_KEY" \
  --factory-setup-password-output releases/factory-artifacts/replacement-device.setup-password.txt
```

The version is the HAMD product release and must match the application version
published with the same release. Component names remain in artifact filenames,
while the MicroPython runtime is reported separately by the device. This is a
complete ESP32-S3 core firmware image, not a recovery-only image. The frozen
recovery API version is tracked separately in the build lock and firmware
metadata. Increment the release sequence for every distinct signed build.

The helper:

1. verifies the exact pinned MicroPython and ESP-IDF commits and rejects
   tracked changes in either dependency checkout;
2. builds the host `mpy-cross` separately;
3. configures `HAM_ESP32_S3` with `SPIRAM_OCT`;
4. freezes the recovery API and security modules;
5. applies the encrypted 8 MB dual-OTA partition table, Secure Boot v2,
   release-mode flash encryption, NVS encryption, and rollback settings;
6. builds `micropython.bin`, `firmware.bin`, and the USB flash artifacts; and
7. embeds the clean HAMD Git revision inside the signed image content;
8. warns at 85% OTA-slot use, refuses packaging at 95%, and wraps only
   application image `micropython.bin` in the signed `.hamf`.

Core helper options:

| Option | Required | Meaning |
| --- | --- | --- |
| `--micropython-root PATH` | Yes | Root of the MicroPython source checkout containing `ports/esp32`. |
| `--version LABEL` | Yes | HAMD core product-release label stored after confirmation. |
| `--release-sequence N` | Yes | Positive signed sequence; must be greater than the confirmed firmware sequence on every target device. |
| `--output PATH` | Yes | Output `.hamf` path. |
| `--factory-output PATH` | Yes | Full first-flash image path outside the deployable release-site tree; refuses overwrite. |
| `--signing-key PATH` | Yes | Offline ECDSA P-256 private key. |
| `--production-security` | Yes | Explicit acknowledgement of the irreversible first-boot eFuse configuration. |
| `--secure-boot-signing-key PATH` | Yes | Offline ESP-IDF Secure Boot v2 RSA-3072 PEM key. |
| `--factory-setup-password-output PATH` | Yes | New mode-0600 unique setup key output; refuses overwrite. |
| `--allow-version-mismatch` | No | Intentionally bypass both the MicroPython and ESP-IDF build-lock checks. This is unsafe for a normal release and should be reflected in the version label and release notes. |
| `--allow-dirty` | No | Permit an explicitly non-production project build whose provenance is marked dirty. Production releases must use a clean project worktree. |
| `-h`, `--help` | No | Show the current command syntax. |

Do not run `make clean` before the helper as a routine step. It reconfigures the
build and supplies the separately built `mpy-cross`. If ESP-IDF reports a
modified `managed_components` directory, resolve that upstream checkout
explicitly: preserve intentional component changes under `components/`, or use
a clean MicroPython checkout. Do not blindly delete work you intend to keep.

Older project instructions modified upstream
`ports/esp32/boards/ESP32_GENERIC_S3/sdkconfig.board` and copied
`ports/esp32/partitions-8MiB-ota.csv`. The current helper does not use either
legacy modification; it uses the repository-owned `HAM_ESP32_S3` board and a
temporary, automatically cleaned partition-table copy. Review `git status` in
the MicroPython checkout and archive or revert those old edits separately if a
clean upstream source tree is required.

### Alternative: wrap an existing application-only image

If a matching firmware build already exists, wrap its application-only image:

```sh
python3 tools/build_firmware_update.py \
  --input "$MICROPYTHON_ROOT/ports/esp32/build-HAM_ESP32_S3-SPIRAM_OCT-secure/micropython.bin" \
  --output ham-core-1.5.0.hamf \
  --version 1.5.0 \
  --release-sequence 1500 \
  --platform esp32-s3 \
  --max-image-bytes 2097152 \
  --signing-key "$UPDATE_SIGNING_KEY"
```

Wrapper options:

| Option | Required | Meaning |
| --- | --- | --- |
| `--input PATH` | Yes | ESP application-only `micropython.bin` or distributed `.app-bin`; its first byte must be the ESP image magic `0xe9`. |
| `--output PATH` | Yes | Output `.hamf` path. |
| `--version LABEL` | Yes | HAMD core product-release label. |
| `--release-sequence N` | Yes | Positive signed sequence; must be greater than the confirmed firmware sequence on every target device. |
| `--platform esp32-s3` | No | Target platform; `esp32-s3` is the only accepted/current value and is the default. |
| `--signing-key PATH` | Yes | Offline ECDSA P-256 private key. |
| `--max-image-bytes N` | No | Maximum accepted input image size; defaults to 2,097,152 bytes and should match an OTA slot. |
| `-h`, `--help` | No | Show the current command syntax. |

Never wrap or upload `firmware.bin`. It is the combined initial-USB image and
contains material for addresses other than one OTA application slot.

### Format transition

Format 6 deliberately has no compatibility bridge. Reflash a matching format-6
factory/core image before installing format-6 application or firmware bundles.

### Step 3: upload, verify, activate, and confirm

1. In **Maintenance > Upgrades**, choose the `.hamf` file in the manual upgrade
   card and select **Upload and verify**.
2. Wait for both upload and flash read-back verification to reach 100%.
3. Confirm the firmware label is staged with status `ready`.
4. Select **Activate firmware and reboot** once.
5. Leave power connected. ESP-IDF boots the inactive OTA partition as a trial.
6. The application confirms the firmware after settings, Wi-Fi, and the
   authenticated portal start successfully. Firmware confirmation deliberately
   does not depend on an external MQTT broker.
7. Reopen the portal, sign in, and confirm:

   - **Core firmware** shows the new HAMD product-release label;
   - **MicroPython version** is `1.28.0` for the current pinned runtime;
   - **Staged version** is `Not staged`;
   - **Update status** is `idle`; and
   - **OTA firmware availability** is `ready`.

The human-readable `.hamf` label appears as **Core firmware**, in update history,
and in the internal `.firmware-version`. The portal's **MicroPython version** is
the runtime's `sys.implementation.version`, so it independently displays
`1.28.0`.

## 3. Combined universal upgrade (`.hamu`)

HAMU packages provide one upload and one activation action for a matched core
and application release. Each embedded `.hamf` and `.hamd` retains its own
signature. The outer HAMU manifest is signed separately and binds both files'
versions, sequences, sizes, and SHA-256 digests.

HAMU format 2 also signs the activation order, whether a maintenance window is
required, the paired/independent/manual rollback policy, and the trial timeout.
Because v2 alpha deliberately does not retain the v1 HAMU parser, build new
universal bundles with the v2 tool after installing the v2 alpha core.

Build the component bundles first with the same release sequence, then combine
them:

```sh
python3 tools/build_universal_update.py \
  releases/universal-1.5.0.hamu \
  --firmware releases/ham-core-1.5.0.hamf \
  --application releases/application-1.5.0.hamd \
  --version 1.5.0 \
  --release-sequence 1500 \
  --signing-key "$UPDATE_SIGNING_KEY"
```

Upload the `.hamu` through **Maintenance > Upgrades** or the authenticated core
recovery portal. The device streams the core to the inactive OTA partition,
stages the application in the inactive VFS slot, verifies both inner packages
and the outer binding, then presents **Activate universal update and reboot**.
Progress is reported separately for core writing, core read-back verification,
and application verification.

If either component sequence is already installed, that component is still
read and hash-verified but is not staged again. If neither component is newer,
the package is rejected. Core recovery API versions before 8 and their existing
application portals cannot parse or route HAMU. Install the first HAMU-capable
`.hamf` and its matching `.hamd` separately as a one-time bootstrap. Subsequent
matched core-and-application releases can be installed using only `.hamu`.

## 4. Installing a new ESP32-S3

A new device cannot become OTA-capable by uploading `.hamf`. It must first
receive the bootloader, OTA partition table, initial OTA metadata, and recovery-
enabled MicroPython application over USB. The VFS application/configuration is
then copied over serial.

### Step 1: prepare the pinned source trees

Clone or select MicroPython `v1.28.0`, including submodules:

```sh
git clone --recursive https://github.com/micropython/micropython.git \
  "$MICROPYTHON_ROOT"
cd "$MICROPYTHON_ROOT"
git checkout e0e9fbb17ed6fd06bb76e266ae554784c9c80804
git submodule update --init --recursive
```

Clone or select ESP-IDF `v5.5.1`, including submodules, then install ESP32-S3
tools. If these trees already exist, verify their versions instead of cloning
over them:

```sh
git clone --recursive --branch v5.5.1 \
  https://github.com/espressif/esp-idf.git "$IDF_ROOT"
cd "$IDF_ROOT"
git checkout fcae32885b0296b32044cb99ecbdc50d98dddb83
git submodule update --init --recursive
./install.sh esp32s3
source "$IDF_ROOT/export.sh"
idf.py --version
```

Do not bypass TLS certificate verification to work around an `install.sh`
download failure. Repair the Mac/Python CA trust or use an approved trusted
network, then rerun the installer.

### Step 2: prepare the factory catalogue and signed applications

From the project root:

1. Set the production HTTPS release-manifest endpoint in `factory_config.py`.
   Leave it empty if first boot will use signed bundle upload. Query endpoints
   and templates such as `https://updates.example/{channel}/latest.json` are
   supported.
2. Build one profile-free signed `.hamd` runtime. Its `app_settings.json` is
   mandatory signed content; module settings may be offered as an optional
   activation group or omitted.
3. Prepare the trusted Home IoT CA certificate in DER format. The wizard can
   use the CA's ACME directory to issue the portal keypair automatically, or
   accept a manually supplied DER certificate/key as a fallback.
4. Do not create `secrets.py`; the wizard stores credentials in encrypted NVS.

### Step 3: build all firmware artifacts

```sh
source "$IDF_ROOT/export.sh"
cd "$HAM_PROJECT_ROOT"
python3 tools/generate_secure_boot_key.py \
  --esp-idf-root "$IDF_ROOT" --output "$SECURE_BOOT_KEY"
python3 tools/build_micropython_firmware.py \
  --micropython-root "$MICROPYTHON_ROOT" \
  --version 1.5.0 \
  --release-sequence 1500 \
  --output releases/release-site-1.5.0/bundles/ham-core-1.5.0.hamf \
  --factory-output releases/factory-artifacts/ham-core-1.5.0.factory.bin \
  --signing-key "$UPDATE_SIGNING_KEY" \
  --production-security \
  --secure-boot-signing-key "$SECURE_BOOT_KEY" \
  --factory-setup-password-output releases/factory-artifacts/device-001.setup-password.txt
```

The helper refuses an insecure production package. It writes a `.factory.bin`
first-flash image containing an encrypted NVS partition, a unique setup AP key,
and only the public OTA verification key. It also writes the setup key to the
requested mode-0600 file for the device label/password manager. It refuses to
overwrite that file. First boot permanently enables Secure Boot v2, AES-256
release-mode flash encryption, NVS encryption, and JTAG lockdown.

The resulting output layout keeps update-server files and device-specific
factory material separate:

```text
releases/
├── release-site-<version>/
│   ├── <channel>/latest.json
│   └── bundles/
└── factory-artifacts/
```

Publish only the contents of `release-site-<version>`. Never publish the
factory image or its paired setup-password file.

### Step 4: locate and flash the serial device

Connect the board by its native USB port. On macOS, list likely ports:

```sh
ls /dev/cu.usb*
```

Set `DEVICE_PORT` to the correct result. The following erase is destructive and
is appropriate only for a new device or after all existing VFS credentials and
configuration have been backed up:

```sh
export FIRMWARE_BUILD_DIR="$MICROPYTHON_ROOT/ports/esp32/build-HAM_ESP32_S3-SPIRAM_OCT-secure"
cd "$FIRMWARE_BUILD_DIR"
python -m esptool \
  --chip esp32s3 \
  --port "$DEVICE_PORT" \
  --baud 460800 \
  --before default_reset \
  --after hard_reset \
  erase_flash
```

Flash the self-contained factory image produced by the helper:

```sh
python -m esptool \
  --chip esp32s3 \
  --port "$DEVICE_PORT" \
  --baud 460800 \
  --before default_reset \
  --after hard_reset \
  write_flash 0x0 "$HAM_PROJECT_ROOT/releases/factory-artifacts/ham-core-1.5.0.factory.bin"
```

The options mean: select the ESP32-S3 ROM protocol, use the specified serial
port at 460800 baud, reset into the bootloader before writing, reset normally
after writing. Do not substitute the unmodified MicroPython `firmware.bin`: the
packaged `.factory.bin` also contains this device's encrypted factory NVS.

### Step 5: complete the first-boot wizard

After the first reset, connect to `HAMD-Setup-xxxxxx` using the password from
`device-001.setup-password.txt` and browse to `http://192.168.4.1`. Enter the
device name, Wi-Fi, portal, and independently confirmed recovery credentials.
The device generates a hostname-matched self-signed HTTPS identity after the
browser supplies current UTC. Continue with that fallback, enroll with ACME,
or atomically replace it with manually uploaded DER files. Automatic portal
transport selects HTTPS whenever a certificate and key are installed.

The factory/reseed workflow stages a signed `.hamd` before the setup AP is
presented. Certificate completion verifies that preloaded application, commits
setup, erases the one-time setup AP key, and reboots into the trial application
slot. If verification fails, the wizard offers the configured HTTPS release
endpoint or manual `.hamd` upload as a recovery path. The browser polls the
permanent portal after restart and opens its login page when ready.

After reboot, sign in to the HTTPS portal. Configure Wi-Fi and device identity
under **System > Network**, MQTT under **System > MQTT**, and the release
channel under **Maintenance > Upgrades**. Portal transport is under **System >
Portal**; administrator identity and password replacement share **User >
Account**, and legacy direct password URLs are disabled. Saving a network
change starts a three-minute trial: an authenticated
login confirms it, while an unconfirmed device restores the complete previous
NVS configuration on the next boot.

Store the recovery AP and console passwords in the operator's password manager.
The signed application bundle may be preloaded over USB by the factory/reseed
tool. Credentials and private OTA signing keys are never copied to the device.

To recommission an installed device, use **Maintenance > Factory default**.
Supply the current administrator password, type the exact reset confirmation,
and choose a new setup-AP password twice. On reboot the frozen recovery layer
clears user settings, module configuration, certificates/ACME state, pending
updates, and local update history, then starts `HAMD-Setup-xxxxxx`. Confirmed
application slots, the signed core, release counters, and the OTA verification
public key are deliberately retained. This reset does not rotate the offline
update-signing key or undo Secure Boot/flash-encryption eFuses.

### Step 6: verify OTA and recovery

Use `mpremote` to run a short MicroPython diagnostic:

```sh
mpremote connect "$DEVICE_PORT" exec \
  "import sys,esp32,recovery_boot; p=esp32.Partition(esp32.Partition.RUNNING); n=p.get_next_update(); print(sys.implementation); print('running',p.info()); print('inactive',n.info() if n else None); print('recovery API',getattr(recovery_boot,'RECOVERY_API_VERSION',1))"
mpremote connect "$DEVICE_PORT" reset
```

Expected results:

- `_machine` contains `HAMD ESP32-S3 OTA with ESP32S3`;
- the running partition is `ota_0` or `ota_1`;
- `get_next_update()` returns the other OTA slot;
- the runtime version is `(1, 28, 0, ...)`; and
- recovery API is `6`.

Then open the portal, sign in, and verify application/MQTT/module health.
The portal's OTA availability must be `ready`. `No inactive OTA partition`
means the complete `flash_args` installation did not occur; a `.hamf` upload
cannot repair the partition table.

## Validation before release

Run host tests with host Python:

```sh
cd "$HAM_PROJECT_ROOT"
python3 tools/check_repository_hygiene.py
python3 tools/validate_json_schemas.py
python3 tools/check_accessibility.py
python3 -m unittest discover -s tests -v
python3 -m py_compile tools/*.py tests/*.py
```

The CI release gate runs the same hygiene and schema checks and performs a
complete secure ESP32-S3 firmware build using the pinned MicroPython commit and
ESP-IDF container. Hygiene rejects
tracked credentials, private keys, Python caches, and platform metadata. The
schema gate validates application policy, module configuration, and every
published `latest.json`. Production builds embed the source revision in content
covered by the signed application/core hashes. Publication requires the same
clean revision, revalidates all bundle payload hashes, and records the revision
in the signed descriptor notes.

Compile device runtime files with the pinned MicroPython compiler, not CPython:

```sh
export MPY_CROSS="$MICROPYTHON_ROOT/mpy-cross/build/mpy-cross"
for file in *.py device_modules/*.py services/*.py lib/*.py lib/primitives/*.py lib/uhcsr04/*.py; do
  "$MPY_CROSS" "$file" -o /tmp/ham-device-check.mpy || break
done
```

Generate release evidence beside the signed artifacts:

```sh
python3 tools/generate_sbom.py --version 2.0.0-alpha.1 \
  --output releases/hamd-2.0.0-alpha.1.cdx.json
python3 tools/generate_provenance.py --version 2.0.0-alpha.1 \
  --output releases/hamd-2.0.0-alpha.1.provenance.json \
  releases/application-2.0.0-alpha.1.hamd \
  releases/ham-core-2.0.0-alpha.1.hamf \
  releases/universal-2.0.0-alpha.1.hamu
```

Run `tools/hil_qualify.py` with the enrolled fleet mTLS identity to record the
device API latency and required v2 endpoint checks in a JSON qualification
report. The interruption, rollback, DST and local-midnight cases remain manual
fixture steps for the single physical test device.

This compile loop intentionally targets runtime modules. Hardware behavior,
ESP32 partition switching, power interruption, Wi-Fi failure, network-trial
rollback, certificate-set rollback, and certificate validity still require a
physical-device release test. MQTT failure must leave the authenticated portal
available; MQTT is deliberately not part of update health.

Before tagging an RC, also rotate every Wi-Fi, MQTT, setup, recovery, and portal
credential that has ever appeared in a local plaintext file or repository
history. Removing a file from the current tree does not invalidate a disclosed
secret. Keep the offline update-signing private key and production Secure Boot
key outside this repository and back them up separately.

## Common recovery checks

When `device.wifi_recovery_enabled` is true, application startup exceptions or
two consecutive missed startup health checks boot the frozen
`HAMD-Recovery-xxxxxx` access point. Connect with the provisioned WPA2 key,
browse to `http://192.168.4.1`, then authenticate with the different recovery-
console password. The
minimal console can repair Wi-Fi credentials, retry or roll back the application,
and upload signed application/core bundles. It does not expose normal device
controls or accept protected configuration bundles.

Application and firmware trials retain priority over the console: failed
application trials restore shared-file backups and roll back, while an
unconfirmed core that cannot associate with Wi-Fi is left for ESP-IDF rollback.
The console requires the separately provisioned `/.update-verification-key` before
accepting uploads and times out after 15 minutes.

- **`idf.py: command not found`**: source the actual pinned
  `"$IDF_ROOT/export.sh"` in the current terminal.
- **`source: no such file or directory`**: `IDF_ROOT` points at the wrong
  checkout; locate the directory containing `export.sh`.
- **`mpremote` cannot connect**: close any IDE/terminal currently holding the
  serial port, reconnect USB, and run `mpremote connect list`.
- **Portal `401 Unauthorized`**: reload the portal and sign in again.
- **Portal `403 Forbidden`**: refresh/re-authenticate so the session and CSRF
  value match; update uploads send the CSRF value in a request header.
- **No activation button**: the staged status must be `ready`, not `idle`,
  `activating`, or `trial`; review update history for the rejection detail.
- **No inactive OTA partition**: perform the one-time complete USB flash using
  the generated `flash_args`.
- **Trial repeatedly rolls back**: inspect portal history and the serial log.
  Application and core trials require Wi-Fi plus successful authenticated
  portal startup; an unavailable MQTT broker must not roll back a healthy
  locally repairable release.
