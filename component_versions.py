"""Versions used to decide whether an application release affects this device.

Increment ``RUNTIME_VERSION`` for changes outside one isolated device driver.
Each production driver owns its own ``MODULE_VERSION`` integer.
"""

PRODUCT_VERSION = '3.0.0-alpha.9'
RUNTIME_VERSION = 108
DRIVER_API_VERSION = 2
EVENT_API_VERSION = 2
FLEET_API_VERSION = 1
