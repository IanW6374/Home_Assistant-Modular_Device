# ESP32-S3 installation and upgrade guide

This guide applies to the supported ESP32-S3-DevKitC-1-N8R8 target. The
current build is pinned by `firmware/build-lock.json` to:

| Component | Required value |
| --- | --- |
| MicroPython | `v1.28.0` |
| ESP-IDF | `v5.5.1` |
| Project board | `HAM_ESP32_S3` |
| Board variant | `SPIRAM_OCT` |
| Flash/PSRAM | 8 MB / 8 MB Octal |
| OTA application slots | `ota_0` and `ota_1`, 2 MiB each |
| Frozen recovery API | `2` |

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
export UPDATE_SIGNING_KEY=/path/to/private/update.signing-key
cd "$HAM_PROJECT_ROOT"
```

Keep every version label unique. Reusing a confirmed firmware label is rejected
because it makes staged/running state ambiguous.

## Before any remote update

1. Confirm the portal shows the expected **App version**, **MicroPython
   version**, **Update status: idle**, and **OTA firmware availability: ready**.
2. Keep the device powered throughout upload, verification, activation, and
   reboot.
3. Use the tokenised URL for the first request:

   ```text
   https://<device-ip>:8443/?token=<web_portal_token>
   ```

   HTTP uses port 8080 by default. The portal removes the token from the URL
   and retains authentication in an HttpOnly session cookie. After a reboot,
   open the tokenised URL again if the browser reports `401 Unauthorized`.
4. Prefer HTTPS. Protected updates containing Wi-Fi/MQTT secrets, certificates,
   or private keys must not be sent over untrusted HTTP.
5. Confirm the update controls are enabled in `device_settings.json`:

   ```json
   {
     "web_portal": {
       "enabled": true,
       "updates_enabled": true,
       "update_max_bytes": 4194304,
       "allow_protected_updates": true,
       "firmware_updates_enabled": true,
       "firmware_update_max_bytes": 4194304
     }
   }
   ```

`allow_protected_updates` may remain `false` unless an update must replace
settings, secrets, or certificates.

## Update signing

Signing is optional only while no signing key has been provisioned on the
device. Once `.update-signing-key` exists in the device VFS, both unsigned
`.hamd` and unsigned `.hamf` bundles are rejected.

Generate and validate a 32-byte key on the host:

```sh
cd "$HAM_PROJECT_ROOT"
python3 tools/provision_update_signing.py \
  --key "$UPDATE_SIGNING_KEY" \
  --generate
```

For a mounted VFS, provision it with:

```sh
python3 tools/provision_update_signing.py \
  --key "$UPDATE_SIGNING_KEY" \
  --mount /path/to/device-vfs
```

For a normal serial-connected ESP32-S3, provision it with `mpremote`:

```sh
mpremote connect "$DEVICE_PORT" fs cp \
  "$UPDATE_SIGNING_KEY" :.update-signing-key
```

The key and `secrets.py` are shared VFS files, not files inside application
slot `a` or `b`. A protected application update backs up a shared file before
replacing it and restores it if the trial cannot reconnect and confirm.

Signing helper options:

| Option | Required | Meaning |
| --- | --- | --- |
| `--key PATH` | Yes | Host key file containing exactly 64 hexadecimal characters. |
| `--generate` | No | Create a new key; refuses to overwrite an existing key. |
| `--mount PATH` | No | Copy the key to `.update-signing-key` on a mounted VFS. Without it, the helper only generates/validates the host key. |
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
  --version application-1.5.0 \
  --signing-key "$UPDATE_SIGNING_KEY"
```

The builder analyses the active `device_settings.json` and selected module
settings file. It recursively includes every required driver dependency and
prints every packaged path. Unknown device subclasses and missing dependencies
stop the build.

To include the active settings as optional activation choices:

```sh
python3 tools/build_update.py \
  application-1.5.0-with-settings.hamd \
  --version application-1.5.0 \
  --include-settings \
  --signing-key "$UPDATE_SIGNING_KEY"
```

To build for non-default settings files:

```sh
python3 tools/build_update.py \
  application-1.5.0-ems.hamd \
  --version application-1.5.0-ems \
  --device-settings device_settings.ems.json \
  --module-settings module_settings.ems.json \
  --signing-key "$UPDATE_SIGNING_KEY"
```

Supplying either settings-path option causes both normalised settings files to
be packaged. The installed names are always `device_settings.json` and
`module_settings.json`, and the packaged device settings are rewritten to
select `module_settings.json`.

To build a protected maintenance bundle:

```sh
python3 tools/build_update.py \
  credentials-2026-07.hamd \
  --version credentials-2026-07 \
  --protected-only \
  --certificate home-ca.der \
  --certificate web.crt.der \
  --certificate web.key.der \
  --signing-key "$UPDATE_SIGNING_KEY"
```

### Application builder options

| Argument | Required | Meaning |
| --- | --- | --- |
| `output` | Yes | Positional output path; use a `.hamd` suffix. |
| `--version LABEL` | Yes | Unique application or maintenance version label. |
| `--include-protected` | No | Include repository-root `secrets.py` if it exists. Requires device protected-update permission when activated. |
| `--protected-only` | No | Exclude application files and build only secrets/certificate maintenance content. It implicitly collects local `secrets.py` and cannot be combined with settings options. |
| `--include-settings` | No | Include the default `device_settings.json` and its selected module settings file. |
| `--device-settings PATH` | No | Analyse this non-default device settings file and package it as `device_settings.json`. |
| `--module-settings PATH` | No | Analyse this non-default module settings file and package it as `module_settings.json`. |
| `--certificate PATH` | No | Add a certificate/key as `certs/<basename>`. Repeat once per file. Supplying it makes the bundle protected. |
| `--signing-key PATH` | No | Sign with a 32-byte raw or 64-character hexadecimal HMAC key. Required in practice after device provisioning. |
| `-h`, `--help` | No | Show the current command syntax. |

### Step 2: upload and verify

1. Open **Software update** in the authenticated portal.
2. Select the `.hamd` file with the single update chooser.
3. Select **Upload and verify**.
4. Wait for **Uploading** to reach 100%, then for **Verifying** to reach 100%.
   Do not manually refresh while an upload is active. Normal portal refresh is
   paused automatically.
5. Confirm **Staged version** shows the application label and **Update status**
   is `ready`.

### Step 3: choose optional shared files

The portal shows switches only for optional groups present in the bundle:

- **Device settings** installs `device_settings.json`.
- **Module settings** installs `module_settings.json`.
- **Secrets** installs `secrets.py`.
- **Certificates** installs selected files under `/certs`.

Application/runtime files are always applied. Optional switches default off.
Select only the shared files intended for this device.

### Step 4: activate and verify health

1. Select **Activate and reboot** once.
2. Leave the device powered and do not interrupt its serial REPL during the
   trial. The inactive application slot is prepared and the module reboots.
3. Allow up to three minutes for local startup plus Wi-Fi, portal, and MQTT
   health confirmation.
4. Reopen the tokenised portal URL if its previous session was lost.
5. Confirm the new **App version**, **Update status: idle**, a non-legacy
   **Active slot**, and expected module health/MQTT state.

If activation is interrupted, the next boot removes the unconfirmed slot and
restores backed-up shared files. The portal update history records staged,
trial, confirmed, rejected, activation-failed, and rollback events.

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
  --version micropython-1.28.0-recovery-3 \
  --output micropython-1.28.0-recovery-3.hamf \
  --signing-key "$UPDATE_SIGNING_KEY"
```

The helper:

1. verifies the pinned MicroPython and ESP-IDF versions;
2. builds the host `mpy-cross` separately;
3. configures `HAM_ESP32_S3` with `SPIRAM_OCT`;
4. freezes the recovery API and security modules;
5. applies the 8 MB dual-OTA partition table and rollback setting;
6. builds `micropython.bin`, `firmware.bin`, and the USB flash artifacts; and
7. wraps only application image `micropython.bin` in the signed `.hamf`.

Core helper options:

| Option | Required | Meaning |
| --- | --- | --- |
| `--micropython-root PATH` | Yes | Root of the MicroPython source checkout containing `ports/esp32`. |
| `--version LABEL` | Yes | Unique firmware image label stored after confirmation. |
| `--output PATH` | Yes | Output `.hamf` path. |
| `--signing-key PATH` | No | HMAC key shared with the device. |
| `--allow-version-mismatch` | No | Intentionally bypass both the MicroPython and ESP-IDF build-lock checks. This is unsafe for a normal release and should be reflected in the version label and release notes. |
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
  --input "$MICROPYTHON_ROOT/ports/esp32/build-HAM_ESP32_S3-SPIRAM_OCT/micropython.bin" \
  --output micropython-1.28.0-recovery-3.hamf \
  --version micropython-1.28.0-recovery-3 \
  --platform esp32-s3 \
  --max-image-bytes 2097152 \
  --signing-key "$UPDATE_SIGNING_KEY"
```

Wrapper options:

| Option | Required | Meaning |
| --- | --- | --- |
| `--input PATH` | Yes | ESP application-only `micropython.bin` or distributed `.app-bin`; its first byte must be the ESP image magic `0xe9`. |
| `--output PATH` | Yes | Output `.hamf` path. |
| `--version LABEL` | Yes | Unique firmware label. |
| `--platform esp32-s3` | No | Target platform; `esp32-s3` is the only accepted/current value and is the default. |
| `--signing-key PATH` | No | HMAC signing key. |
| `--max-image-bytes N` | No | Maximum accepted input image size; defaults to 2,097,152 bytes and should match an OTA slot. |
| `-h`, `--help` | No | Show the current command syntax. |

Never wrap or upload `firmware.bin`. It is the combined initial-USB image and
contains material for addresses other than one OTA application slot.

### Step 3: upload, verify, activate, and confirm

1. In **Software update**, choose the `.hamf` file and select **Upload and
   verify**.
2. Wait for both upload and flash read-back verification to reach 100%.
3. Confirm the firmware label is staged with status `ready`.
4. Select **Activate firmware and reboot** once.
5. Leave power connected. ESP-IDF boots the inactive OTA partition as a trial.
6. The frozen recovery layer confirms the firmware after the application entry,
   settings, and event loop start locally. Firmware confirmation deliberately
   does not depend on an external MQTT broker.
7. Reopen the tokenised portal URL and confirm:

   - **MicroPython version** is `1.28.0` for the current pinned runtime;
   - **Staged version** is `Not staged`;
   - **Update status** is `idle`; and
   - **OTA firmware availability** is `ready`.

The human-readable `.hamf` label appears in firmware update history and the
internal `.firmware-version`; the portal's **MicroPython version** is the
runtime's `sys.implementation.version`, so it displays `1.28.0` rather than the
long recovery label.

## 3. Installing a new ESP32-S3

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
git checkout v1.28.0
git submodule update --init --recursive
```

Clone or select ESP-IDF `v5.5.1`, including submodules, then install ESP32-S3
tools. If these trees already exist, verify their versions instead of cloning
over them:

```sh
git clone --recursive --branch v5.5.1 \
  https://github.com/espressif/esp-idf.git "$IDF_ROOT"
cd "$IDF_ROOT"
./install.sh esp32s3
source "$IDF_ROOT/export.sh"
idf.py --version
```

Do not bypass TLS certificate verification to work around an `install.sh`
download failure. Repair the Mac/Python CA trust or use an approved trusted
network, then rerun the installer.

### Step 2: prepare device-specific files

From the project root:

1. Set the device identity, correct module file, ESP32-S3 GPIOs, portal/update
   settings, and watchdog in `device_settings.json`.
2. Configure the physical modules in `module_settings.json`.
3. Create `secrets.py` from `examples/secrets.example.py`, including Wi-Fi,
   MQTT, `web_portal_token`, and `recovery_ap_password`.
4. Put any MQTT/portal certificates in a local `certs/` directory and make the
   configured device paths start with `/certs/`.
5. Keep `watchdog_timeout_ms` at `0` during first bring-up; enable the intended
   production timeout after connectivity is stable.

### Step 3: build all firmware artifacts

```sh
source "$IDF_ROOT/export.sh"
cd "$HAM_PROJECT_ROOT"
python3 tools/build_micropython_firmware.py \
  --micropython-root "$MICROPYTHON_ROOT" \
  --version micropython-1.28.0-recovery-3 \
  --output micropython-1.28.0-recovery-3.hamf \
  --signing-key "$UPDATE_SIGNING_KEY"
```

Omit `--signing-key` only if no device key will be provisioned yet. The `.hamf`
is for future OTA use; the first USB install uses the generated `flash_args`.

### Step 4: locate and flash the serial device

Connect the board by its native USB port. On macOS, list likely ports:

```sh
ls /dev/cu.usb*
```

Set `DEVICE_PORT` to the correct result. The following erase is destructive and
is appropriate only for a new device or after all existing VFS credentials and
configuration have been backed up:

```sh
export FIRMWARE_BUILD_DIR="$MICROPYTHON_ROOT/ports/esp32/build-HAM_ESP32_S3-SPIRAM_OCT"
cd "$FIRMWARE_BUILD_DIR"
python -m esptool \
  --chip esp32s3 \
  --port "$DEVICE_PORT" \
  --baud 460800 \
  --before default_reset \
  --after hard_reset \
  erase_flash
```

Flash all generated offsets from the build's `flash_args`:

```sh
python -m esptool \
  --chip esp32s3 \
  --port "$DEVICE_PORT" \
  --baud 460800 \
  --before default_reset \
  --after hard_reset \
  write_flash @flash_args
```

The options mean: select the ESP32-S3 ROM protocol, use the specified serial
port at 460800 baud, reset into the bootloader before writing, reset normally
after writing, and load the bootloader/partition/OTA/application address list
from `flash_args`.

### Step 5: install `mpremote` and deploy the VFS

Install the official MicroPython serial filesystem tool on the host:

```sh
python3 -m pip install mpremote
mpremote connect list
```

Copy recovery fallbacks, application code, and settings before installing
`main.py`. Copying the launcher last avoids starting a half-deployed
application if the device resets during transfer:

```sh
cd "$HAM_PROJECT_ROOT"
mpremote connect "$DEVICE_PORT" fs cp \
  recovery_boot.py app_update.py firmware_update.py hardware_platform.py \
  update_security.py update_support.py wifi_recovery.py HA-Device.py \
  release_update.py settings_loader.py local_display.py web_portal.py \
  device_settings.json module_settings.json secrets.py :

mpremote connect "$DEVICE_PORT" fs cp -r device_modules :
mpremote connect "$DEVICE_PORT" fs cp -r lib :
```

If certificates are configured:

```sh
mpremote connect "$DEVICE_PORT" fs mkdir :certs
mpremote connect "$DEVICE_PORT" fs cp certs/home-ca.der :certs/home-ca.der
mpremote connect "$DEVICE_PORT" fs cp certs/web.crt.der :certs/web.crt.der
mpremote connect "$DEVICE_PORT" fs cp certs/web.key.der :certs/web.key.der
```

Provision the signing key before first boot if signed updates are required:

```sh
mpremote connect "$DEVICE_PORT" fs cp \
  "$UPDATE_SIGNING_KEY" :.update-signing-key
```

Finally install the permanent launcher and reset:

```sh
mpremote connect "$DEVICE_PORT" fs cp main.py :main.py
mpremote connect "$DEVICE_PORT" reset
```

The host helper `tools/deploy.py MOUNT [--secrets]` remains available only for
environments that expose the MicroPython VFS as a mounted directory. A normal
ESP32-S3 serial deployment should use `mpremote`.

Mounted-deployment helper options:

| Argument | Required | Meaning |
| --- | --- | --- |
| `MOUNT` | Yes | Positional path to the mounted MicroPython filesystem. |
| `--secrets` | No | Also copy repository-root `secrets.py` when present. |
| `-h`, `--help` | No | Show the current command syntax. |

### Step 6: verify OTA and recovery

Use `mpremote` to run a short MicroPython diagnostic:

```sh
mpremote connect "$DEVICE_PORT" exec \
  "import sys,esp32,recovery_boot; p=esp32.Partition(esp32.Partition.RUNNING); n=p.get_next_update(); print(sys.implementation); print('running',p.info()); print('inactive',n.info() if n else None); print('recovery API',getattr(recovery_boot,'RECOVERY_API_VERSION',1))"
mpremote connect "$DEVICE_PORT" reset
```

Expected results:

- `_machine` contains `HAM ESP32-S3 OTA with ESP32S3`;
- the running partition is `ota_0` or `ota_1`;
- `get_next_update()` returns the other OTA slot;
- the runtime version is `(1, 28, 0, ...)`; and
- recovery API is `2`.

Then open the tokenised portal URL and verify application/MQTT/module health.
The portal's OTA availability must be `ready`. `No inactive OTA partition`
means the complete `flash_args` installation did not occur; a `.hamf` upload
cannot repair the partition table.

## Validation before release

Run host tests with host Python:

```sh
cd "$HAM_PROJECT_ROOT"
python3 -m unittest discover -s tests -v
python3 -m py_compile tools/*.py tests/*.py
```

Compile device runtime files with the pinned MicroPython compiler, not CPython:

```sh
export MPY_CROSS="$MICROPYTHON_ROOT/mpy-cross/build/mpy-cross"
for file in *.py device_modules/*.py lib/*.py lib/primitives/*.py lib/uhcsr04/*.py; do
  "$MPY_CROSS" "$file" -o /tmp/ham-device-check.mpy || break
done
```

This compile loop intentionally targets runtime modules. Hardware behavior,
ESP32 partition switching, power interruption, Wi-Fi failure, MQTT failure,
and certificate validity still require a physical-device release test.

## Common recovery checks

- **`idf.py: command not found`**: source the actual pinned
  `"$IDF_ROOT/export.sh"` in the current terminal.
- **`source: no such file or directory`**: `IDF_ROOT` points at the wrong
  checkout; locate the directory containing `export.sh`.
- **`mpremote` cannot connect**: close any IDE/terminal currently holding the
  serial port, reconnect USB, and run `mpremote connect list`.
- **Portal `401 Unauthorized`**: authenticate again with the tokenised URL.
- **Portal `403 Forbidden`**: refresh/re-authenticate so the session and CSRF
  value match; update uploads send the CSRF value in a request header.
- **No activation button**: the staged status must be `ready`, not `idle`,
  `activating`, or `trial`; review update history for the rejection detail.
- **No inactive OTA partition**: perform the one-time complete USB flash using
  the generated `flash_args`.
- **Trial repeatedly rolls back**: inspect portal history and the serial log.
  Application trials require Wi-Fi, portal (when enabled), and MQTT; core
  firmware trials require only local recovery/application startup.
