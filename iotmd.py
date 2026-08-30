"""Compact application entry retained for recovery-core compatibility.

The substantial runtime is shipped as ``iotmd_runtime.mpy`` in production
bundles. Keeping this source entry deliberately small avoids the large
contiguous heap allocation previously required during trial boot.
"""

import iotmd_runtime


set_main_device_error = iotmd_runtime.set_main_device_error
iotmd_runtime.run_application()
