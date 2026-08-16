#!/usr/bin/env python3
"""Stage a signed HAMD application bundle over USB without erasing user state."""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description='Copy and stage a signed .hamd bundle over the MicroPython USB REPL'
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
    if bundle.read_bytes()[:6] != b'HAMD1\n':
        raise SystemExit('application bundle has an invalid header')

    tools_dir = Path(args.micropython_root).resolve() / 'tools'
    if not (tools_dir / 'pyboard.py').is_file():
        raise SystemExit('MicroPython pyboard tool not found: ' + str(tools_dir))
    sys.path.insert(0, str(tools_dir))
    import pyboard

    remote_path = '/.hamd-usb-application.hamd'
    board = pyboard.Pyboard(args.device)
    try:
        board.enter_raw_repl(soft_reset=False)
        board.exec_(
            "import machine\n"
            "_hamd_wdt=machine.WDT(0)\n"
            "def _hamd_feed():\n"
            " _hamd_wdt.feed()\n"
            "_hamd_upload=open('" + remote_path + "','wb')\n"
            "_hamd_write=_hamd_upload.write"
        )
        total = bundle.stat().st_size
        written = 0
        with bundle.open('rb') as stream:
            while True:
                chunk = stream.read(512)
                if not chunk:
                    break
                board.exec_('_hamd_write(' + repr(chunk) + ')\n_hamd_feed()')
                written += len(chunk)
                if written == total or written % (64 * 1024) < 512:
                    print('copied', written, 'of', total)
        board.exec_('_hamd_upload.close()\n_hamd_feed()')

        stage_code = """
import os
try:
 import uasyncio as _hamd_asyncio
except ImportError:
 import asyncio as _hamd_asyncio
import app_update as _hamd_application
_hamd_source=open('%s','rb')
class _HamdReader:
 async def read(self,count):
  _hamd_feed()
  return _hamd_source.read(count)
async def _hamd_progress(phase,completed,total):
 _hamd_feed()
async def _hamd_stage():
 return await _hamd_application.receive_bundle(
  _HamdReader(),%d,progress_callback=_hamd_progress)
try:
 print(_hamd_asyncio.run(_hamd_stage()))
finally:
 _hamd_source.close()
 os.remove('%s')
""" % (remote_path, total, remote_path)
        result = board.exec_(stage_code, timeout=180)
        print(result.decode().strip())
        print('signed application staged and verified')

        if args.activate:
            print('resetting to activate the staged application')
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
