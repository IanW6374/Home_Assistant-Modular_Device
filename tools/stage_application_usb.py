#!/usr/bin/env python3
"""Stage a signed IoTMD application bundle over USB without erasing user state."""

import argparse
import sys
import time
from pathlib import Path


TRANSFER_CHUNK_BYTES = 4096
TRANSFER_PHASE_BYTES = 192 * 1024
USB_MAINTENANCE_WATCHDOG_TIMEOUT_MS = 300000


def main():
    parser = argparse.ArgumentParser(
        description='Copy and stage a signed .iotapp bundle over the MicroPython USB REPL'
    )
    parser.add_argument('--device', required=True)
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--micropython-root', required=True)
    parser.add_argument(
        '--activate', action='store_true',
        help='reset after staging so recovery activates the verified application'
    )
    args = parser.parse_args()

    bundle = Path(args.bundle).resolve()
    if not bundle.is_file():
        raise SystemExit('application bundle not found: ' + str(bundle))
    if bundle.read_bytes()[:6] != b'IOTA1\n':
        raise SystemExit('application bundle has an invalid header')

    tools_dir = Path(args.micropython_root).resolve() / 'tools'
    if not (tools_dir / 'pyboard.py').is_file():
        raise SystemExit('MicroPython pyboard tool not found: ' + str(tools_dir))
    sys.path.insert(0, str(tools_dir))
    import pyboard

    remote_path = '/.iotapp-usb-application.iotapp'

    def open_maintenance_session():
        board = pyboard.Pyboard(args.device)
        board.enter_raw_repl(soft_reset=False)
        board.exec_(
            "import machine\n"
            "_iotmd_wdt=machine.WDT(0,timeout=" +
            str(USB_MAINTENANCE_WATCHDOG_TIMEOUT_MS) + ")\n"
            "def _iotmd_feed():\n"
            " _iotmd_wdt.feed()\n"
            "_iotmd_feed()"
        )
        return board

    def reset_and_reconnect(board):
        try:
            board.exec_('import machine\nmachine.reset()', timeout=5)
        except (OSError, pyboard.PyboardError):
            pass
        finally:
            board.close()
        last_error = None
        for _attempt in range(12):
            time.sleep(1)
            try:
                return open_maintenance_session()
            except (OSError, pyboard.PyboardError) as exc:
                last_error = exc
        raise last_error or RuntimeError('device did not return after reset')

    board = open_maintenance_session()
    try:
        total = bundle.stat().st_size
        written = 0
        with bundle.open('rb') as stream:
            first_phase = True
            while written < total:
                board.exec_(
                    "_iotmd_upload=open('" + remote_path + "','" +
                    ('wb' if first_phase else 'ab') + "')\n"
                    "_iotmd_write=_iotmd_upload.write"
                )
                first_phase = False
                phase_end = min(total, written + TRANSFER_PHASE_BYTES)
                while written < phase_end:
                    chunk = stream.read(min(TRANSFER_CHUNK_BYTES, phase_end - written))
                    if not chunk:
                        raise RuntimeError('local IoTMD bundle ended early')
                    board.exec_('_iotmd_write(' + repr(chunk) + ')\n_iotmd_feed()')
                    written += len(chunk)
                    if written == total or written % (64 * 1024) < TRANSFER_CHUNK_BYTES:
                        print('copied', written, 'of', total, 'bytes', flush=True)
                board.exec_('_iotmd_upload.close()\n_iotmd_feed()')
                if written < total:
                    print('transfer phase complete; restarting USB session', flush=True)
                    board = reset_and_reconnect(board)
        print('bundle transfer complete; restarting before signed staging', flush=True)
        board = reset_and_reconnect(board)
        print('validating and staging signed application', flush=True)

        # The normal HTTP receiver needs space for both its upload temporary
        # file and the final bundle.  USB has already placed the complete file
        # on the device, so validate it in place and then atomically adopt it as
        # the pending bundle.  This preserves the same signature, release
        # sequence, manifest, and per-file SHA-256 checks without requiring a
        # second full copy on storage-constrained devices.
        stage_code = """
import os
import app_update as _iotmd_application
import recovery_boot as _iotmd_recovery
_iotmd_state=_iotmd_application.update_status()
if _iotmd_state.get('status') == 'ready':
 _iotmd_application.discard_pending_update()
elif _iotmd_state.get('status') != 'idle':
 raise ValueError('cannot replace application update in state '+str(_iotmd_state.get('status')))
_iotmd_manifest=_iotmd_application.validate_bundle('%s',False)
try:
 os.remove(_iotmd_application.BUNDLE_PATH)
except OSError:
 pass
os.rename('%s',_iotmd_application.BUNDLE_PATH)
_iotmd_state=_iotmd_application.stage_bundle(
 _iotmd_application.BUNDLE_PATH,False,manifest=_iotmd_manifest)
_iotmd_recovery.clear_recovery_request()
print(_iotmd_state)
""" % (remote_path, remote_path)
        result = board.exec_(stage_code, timeout=180)
        print('signed staging call returned', flush=True)
        print(result.decode().strip(), flush=True)
        print('signed application staged and verified', flush=True)

        if args.activate:
            result = board.exec_(
                "import app_update,recovery_boot\n"
                "print(app_update.activate_pending())\n"
                "recovery_boot.clear_recovery_request()",
                timeout=180,
            )
            print(result.decode().strip(), flush=True)
            print('resetting to activate the staged application', flush=True)
            try:
                board.exec_('import machine\nmachine.reset()', timeout=5)
            except (OSError, pyboard.PyboardError):
                pass
        else:
            board.exit_raw_repl()
    finally:
        board.close()


if __name__ == '__main__':
    main()
