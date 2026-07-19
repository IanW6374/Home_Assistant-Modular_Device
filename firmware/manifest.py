"""Frozen recovery modules included in ESP32-S3 OTA firmware images."""

# Preserve the standard ESP32 frozen modules, then add the recovery supervisor.
include("$(PORT_DIR)/boards/manifest.py")

module("recovery_boot.py", base_path="..", opt=3)
module("app_update.py", base_path="..", opt=3)
module("firmware_update.py", base_path="..", opt=3)
module("hardware_platform.py", base_path="..", opt=3)
module("update_security.py", base_path="..", opt=3)
module("update_support.py", base_path="..", opt=3)
module("wifi_recovery.py", base_path="..", opt=3)
