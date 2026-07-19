"""Permanent launcher for the frozen recovery supervisor."""

import sys


# MicroPython normally searches the VFS before frozen modules. Prefer the
# rollback-protected firmware copy, while retaining the VFS copy as a fallback
# if a development firmware was built without the project manifest.
if '.frozen' in sys.path:
    sys.path.remove('.frozen')
    sys.path.insert(0, '.frozen')

import recovery_boot


recovery_boot.run()
