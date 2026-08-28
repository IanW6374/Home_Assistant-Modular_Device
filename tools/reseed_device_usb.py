#!/usr/bin/env python3
"""Return a secured IoT-MD device to its shipping first-run state over USB.

This tool is for devices whose Secure Boot and release-mode Flash Encryption
eFuses are already committed.  It deliberately leaves those eFuses and the
flash/NVS encryption keys untouched.  A signed core image is written to the
inactive OTA partition through the running firmware, so ESP-IDF applies the
device's existing flash encryption key as it writes.  A separately signed
application bundle is then staged on the encrypted filesystem.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path


MAGIC = b"IOTC1\n"
APPLICATION_MAGIC = b"IOTA1\n"
BLOCK_SIZE = 4096


def load_bundle(path, signing_key_path, update_security):
    private_key = Path(signing_key_path).expanduser().read_bytes().strip()
    if len(private_key) == 64:
        try:
            private_key = bytes.fromhex(private_key.decode())
        except ValueError:
            pass
    if len(private_key) != 32:
        raise ValueError("update signing key must contain exactly 32 bytes")
    public_key = update_security.public_key_bytes(private_key)
    public_point = (
        int.from_bytes(public_key[:32], "big"),
        int.from_bytes(public_key[32:], "big"),
    )

    bundle_path = Path(path).resolve()
    with bundle_path.open("rb") as stream:
        if stream.read(len(MAGIC)) != MAGIC:
            raise ValueError("firmware bundle has an invalid header")
        manifest_size = int.from_bytes(stream.read(4), "big")
        if not 1 <= manifest_size <= 2048:
            raise ValueError("firmware manifest size is invalid")
        manifest = json.loads(stream.read(manifest_size))
        payload = stream.read()

    signature = str(manifest.get("signature", ""))
    if not update_security.verify_manifest_signature(
        "iotcore", manifest, signature, public_point
    ):
        raise ValueError("firmware manifest signature verification failed")
    if int(manifest.get("format_version", 0)) != 6:
        raise ValueError("only firmware bundle format 6 can be reseeded")
    if manifest.get("target_board", manifest.get("platform")) != "esp32-s3":
        raise ValueError("firmware bundle does not target ESP32-S3")
    if len(payload) != int(manifest.get("size", 0)):
        raise ValueError("firmware payload size does not match its manifest")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != str(manifest.get("sha256", "")).lower():
        raise ValueError("firmware payload digest does not match its manifest")
    if not payload or payload[0] != 0xE9:
        raise ValueError("firmware payload is not an ESP application image")
    if len(payload) % BLOCK_SIZE:
        payload += b"\xff" * (-len(payload) % BLOCK_SIZE)
    return manifest, payload, public_key


def read_setup_password(path):
    password = Path(path).expanduser().read_text().strip()
    if not 16 <= len(password) <= 63:
        raise ValueError("factory setup password must contain 16 to 63 characters")
    return password


def application_bundle_path(path):
    bundle_path = Path(path).resolve()
    if not bundle_path.is_file():
        raise ValueError("signed application bundle does not exist")
    size = bundle_path.stat().st_size
    if size < len(APPLICATION_MAGIC) + 4 or size > 2 * 1024 * 1024:
        raise ValueError("signed application bundle size is invalid")
    with bundle_path.open("rb") as stream:
        if stream.read(len(APPLICATION_MAGIC)) != APPLICATION_MAGIC:
            raise ValueError("application bundle has an invalid header")
    return bundle_path


def open_board(pyboard, device, attempts=1):
    error = None
    for _ in range(attempts):
        try:
            board = pyboard.Pyboard(device)
            board.enter_raw_repl(soft_reset=False)
            return board
        except Exception as exc:
            error = exc
            try:
                board.close()
            except Exception:
                pass
            time.sleep(1)
    raise error or RuntimeError("device did not reconnect")


def exec_text(board, source, timeout=20):
    return board.exec_(source, timeout=timeout).decode().strip()


def reset_board(board):
    try:
        board.exec_("import machine\nmachine.reset()", timeout=3)
    except Exception:
        pass
    try:
        board.close()
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Install a signed core and reset a secured IoT-MD device to first-run setup"
    )
    parser.add_argument("--device", required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument(
        "--application-bundle",
        required=True,
        help="signed .iotapp application to preload for first-run setup",
    )
    parser.add_argument("--micropython-root", required=True)
    parser.add_argument("--setup-password-file", required=True)
    parser.add_argument("--update-signing-key", required=True)
    parser.add_argument(
        "--confirm-erase-user-state",
        action="store_true",
        help="required acknowledgement that application, settings, credentials, certificates and logs are erased",
    )
    args = parser.parse_args()
    if not args.confirm_erase_user_state:
        raise SystemExit("refusing to reseed without --confirm-erase-user-state")

    project = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project))
    import recovery_boot
    import update_security

    tools_dir = Path(args.micropython_root).resolve() / "tools"
    if not (tools_dir / "pyboard.py").is_file():
        raise SystemExit("MicroPython pyboard tool not found: " + str(tools_dir))
    sys.path.insert(0, str(tools_dir))
    import pyboard

    manifest, payload, public_key = load_bundle(
        args.bundle, args.update_signing_key, update_security
    )
    setup_password = read_setup_password(args.setup_password_file)
    application_bundle = application_bundle_path(args.application_bundle)
    expected_digest = str(manifest["sha256"]).lower()

    board = open_board(pyboard, args.device)
    try:
        preflight = exec_text(
            board,
            "import esp32,sys\n"
            "_r=esp32.Partition(esp32.Partition.RUNNING)\n"
            "_t=_r.get_next_update()\n"
            "print(_r.info()[4],_t.info()[4],_t.info()[3],sys.implementation._mpy)",
        )
        print("preflight", preflight)
        fields = preflight.split()
        if len(fields) < 4 or int(fields[-2]) < len(payload):
            raise RuntimeError("inactive OTA partition is unavailable or too small")

        exec_text(
            board,
            "import esp32,machine,uhashlib,ubinascii\n"
            "_iotmd_running=esp32.Partition(esp32.Partition.RUNNING)\n"
            "_iotmd_target=_iotmd_running.get_next_update()\n"
            "_iotmd_wdt=machine.WDT(0)\n"
            "def _iotmd_write(block,data):\n"
            " _iotmd_target.writeblocks(block,data)\n"
            " _iotmd_wdt.feed()",
        )
        total_blocks = len(payload) // BLOCK_SIZE
        for block_number in range(total_blocks):
            start = block_number * BLOCK_SIZE
            block = payload[start : start + BLOCK_SIZE]
            exec_text(
                board,
                "_iotmd_write(%d,%r)" % (block_number, block),
                timeout=30,
            )
            completed = block_number + 1
            if completed == total_blocks or completed % 16 == 0:
                print("written", completed * BLOCK_SIZE, "of", len(payload))

        verified = exec_text(
            board,
            "_iotmd_hash=uhashlib.sha256()\n"
            "_iotmd_buf=bytearray(%d)\n"
            "for _iotmd_block in range(%d):\n"
            " _iotmd_target.readblocks(_iotmd_block,_iotmd_buf)\n"
            " _iotmd_hash.update(_iotmd_buf)\n"
            " _iotmd_wdt.feed()\n"
            "print(ubinascii.hexlify(_iotmd_hash.digest()).decode())"
            % (BLOCK_SIZE, total_blocks),
            timeout=180,
        )
        if verified != hashlib.sha256(payload).hexdigest():
            raise RuntimeError("inactive OTA partition verification failed: " + verified)
        if expected_digest != hashlib.sha256(payload[: int(manifest["size"])]).hexdigest():
            raise RuntimeError("unpadded image verification failed")
        print("verified", expected_digest)

        reset_state = (
            "import esp32,uos as os\n"
            "def _iotmd_remove_tree(path):\n"
            " for item in list(os.ilistdir(path)):\n"
            "  name=item[0]\n"
            "  child=(path.rstrip('/')+'/'+name) or '/'\n"
            "  if item[1]&0x4000:\n"
            "   _iotmd_remove_tree(child)\n"
            "   os.rmdir(child)\n"
            "  else:\n"
            "   os.remove(child)\n"
            "_iotmd_store=esp32.NVS('iotmd_config')\n"
            "for _iotmd_key in ('cfg0','cfg1','active','bootkey','verifykey'):\n"
            " try:_iotmd_store.erase_key(_iotmd_key)\n"
            " except OSError:pass\n"
            "_iotmd_store.set_blob('bootkey',%r)\n"
            "_iotmd_store.set_blob('verifykey',%r)\n"
            "_iotmd_store.commit()\n"
            "_iotmd_remove_tree('/')\n"
            "_iotmd_target.set_boot()\n"
            "print('reseed-ready',_iotmd_target.info()[4])"
            % (setup_password.encode(), public_key)
        )
        print(exec_text(board, reset_state, timeout=60))
        reset_board(board)
        board = None

        # The first boot of a newly selected OTA slot is pending verification.
        # Interrupt the setup server once, validate that the new frozen core is
        # running, mark it valid, then restart into an uninterrupted wizard.
        board = open_board(pyboard, args.device, attempts=45)
        result = exec_text(
            board,
            "import esp32,recovery_boot,credential_store\n"
            "print(esp32.Partition(esp32.Partition.RUNNING).info()[4],"
            "recovery_boot.RECOVERY_API_VERSION,credential_store.is_provisioned(),"
            "len(credential_store.bootstrap_key()))\n"
            "esp32.Partition.mark_app_valid_cancel_rollback()",
            timeout=30,
        )
        print("first boot", result)
        fields = result.split()
        expected_recovery_api = str(recovery_boot.RECOVERY_API_VERSION)
        if len(fields) < 4 or fields[-3:] != [
            expected_recovery_api, "False", str(len(setup_password))
        ]:
            raise RuntimeError("new core did not enter the expected first-run state")

        last_reported = [-1]

        def report_application_progress(written, total):
            bucket = written // 65536
            if written == total or bucket != last_reported[0]:
                last_reported[0] = bucket
                print("application", written, "of", total)

        board.fs_put(
            str(application_bundle),
            ".app-update.bundle",
            chunk_size=512,
            progress_callback=report_application_progress,
        )
        staged = exec_text(
            board,
            "import app_update\n"
            "_iotmd_app=app_update.stage_bundle('.app-update.bundle',False)\n"
            "print(_iotmd_app.get('status'),_iotmd_app.get('version'),"
            "_iotmd_app.get('has_application'),"
            "'app_settings.json' in _iotmd_app.get('selected_paths',()))",
            timeout=180,
        )
        print("preloaded application", staged)
        staged_fields = staged.split()
        if (
            len(staged_fields) < 4 or staged_fields[0] != "ready" or
            staged_fields[-2:] != ["True", "True"]
        ):
            raise RuntimeError(
                "signed application must contain an app and app_settings.json: " +
                staged
            )
        reset_board(board)
        board = None
        print("device reseeded; first-run setup is active")
        print("firmware", manifest.get("version", ""))
        print("application", staged_fields[1])
    finally:
        if board is not None:
            try:
                board.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
