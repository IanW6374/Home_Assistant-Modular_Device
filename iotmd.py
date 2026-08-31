"""Compact application entry retained for recovery-core compatibility.

The substantial runtime is shipped as ``iotmd_runtime.mpy`` in production
bundles. Keeping this source entry deliberately small avoids the large
contiguous heap allocation previously required during trial boot.
"""

import recovery_boot
# Refuse a staged application if its paired core was rolled back first.
REQUIRED_CORE_API = 10
core_api = int(getattr(recovery_boot, 'CORE_API_VERSION', 0) or 0)
if core_api < REQUIRED_CORE_API:
    raise RuntimeError(
        'IoT-MD application requires core API ' + str(REQUIRED_CORE_API) +
        '; installed core API is ' + str(core_api)
    )
import iotmd_runtime

set_main_device_error = iotmd_runtime.set_main_device_error
iotmd_runtime.run_application()
