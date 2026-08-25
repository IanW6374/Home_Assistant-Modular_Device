#!/usr/bin/env python3
"""Stage a signed IoTMD core bundle over USB while servicing the device WDT."""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description='Copy and stage a signed .iotcore bundle over the MicroPython USB REPL'
    )
    parser.add_argument('--device', required=True)
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--micropython-root', required=True)
    parser.add_argument('--activate', action='store_true')
    parser.add_argument(
        '--allow-same-version', action='store_true',
        help=(
            'permit a signed bundle with the current display version; the '
            'device still requires a newer release sequence'
        ),
    )
    args = parser.parse_args()

    bundle = Path(args.bundle).resolve()
    if not bundle.is_file():
        raise SystemExit('firmware bundle not found: ' + str(bundle))
    tools_dir = Path(args.micropython_root).resolve() / 'tools'
    if not (tools_dir / 'pyboard.py').is_file():
        raise SystemExit('MicroPython pyboard tool not found: ' + str(tools_dir))
    sys.path.insert(0, str(tools_dir))
    import pyboard

    remote_path = '/.iotapp-usb-firmware.iotcore'
    board = pyboard.Pyboard(args.device)
    try:
        # Bind the hardware WDT directly. A soft reset would discard the
        # application's Python reference while leaving this watchdog active.
        board.enter_raw_repl(soft_reset=False)
        board.exec_(
            "import machine\n"
            "_iotmd_wdt=machine.WDT(0)\n"
            "def _iotmd_feed():\n"
            " _iotmd_wdt.feed()\n"
            "_iotmd_upload=open('" + remote_path + "','wb')\n"
            "_iotmd_write=_iotmd_upload.write"
        )
        total = bundle.stat().st_size
        written = 0
        with bundle.open('rb') as stream:
            while True:
                chunk = stream.read(512)
                if not chunk:
                    break
                board.exec_('_iotmd_write(' + repr(chunk) + ')\n_iotmd_feed()')
                written += len(chunk)
                if written == total or written % (64 * 1024) < 512:
                    print('copied', written, 'of', total)
        board.exec_('_iotmd_upload.close()\n_iotmd_feed()')

        stage_code = """
import os
try:
 import uasyncio as _iotmd_asyncio
except ImportError:
 import asyncio as _iotmd_asyncio
import firmware_update as _iotmd_firmware
_iotmd_source=open('%s','rb')
_iotmd_running_version=_iotmd_firmware.running_version
class _IoTMDReader:
 async def read(self,count):
  _iotmd_feed()
  return _iotmd_source.read(count)
async def _iotmd_progress(phase,completed,total):
 _iotmd_feed()
async def _iotmd_stage():
 if %r:
  _iotmd_firmware.running_version=lambda fallback='':''
 try:
  return await _iotmd_firmware.receive_bundle(
   _IoTMDReader(),%d,progress_callback=_iotmd_progress)
 finally:
  _iotmd_firmware.running_version=_iotmd_running_version
try:
 print(_iotmd_asyncio.run(_iotmd_stage()))
finally:
 _iotmd_source.close()
 os.remove('%s')
""" % (remote_path, args.allow_same_version, total, remote_path)
        board.exec_(stage_code, timeout=180)
        print('signed firmware staged and verified')

        if args.activate:
            result = board.exec_(
                "import firmware_update as _iotmd_firmware\n"
                "print(_iotmd_firmware.activate_pending())\n"
                "_iotmd_feed()"
            )
            print(result.decode().strip())
            print('firmware marked for trial boot')
        board.exit_raw_repl()
    finally:
        board.close()


if __name__ == '__main__':
    main()
