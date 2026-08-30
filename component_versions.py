"""Versions used to decide whether an application release affects this device.

Increment ``RUNTIME_VERSION`` for changes outside one isolated device driver.
Each production driver owns its own ``MODULE_VERSION`` integer.
"""

PRODUCT_VERSION = '2.3.3'
RUNTIME_VERSION = 81
DRIVER_API_VERSION = 2
EVENT_API_VERSION = 2
FLEET_API_VERSION = 1
