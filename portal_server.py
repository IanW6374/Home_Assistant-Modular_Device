"""Development import for the versioned portal server module.

Production application bundles compile :mod:`web_portal` under this unique
module name.  Older application generations therefore cannot satisfy the
runtime import while a new A/B trial is starting.
"""

from web_portal import start_web_portal


__all__ = ('start_web_portal',)
