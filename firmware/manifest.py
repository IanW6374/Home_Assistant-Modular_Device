"""Frozen recovery modules included in ESP32-S3 OTA firmware images."""

# Preserve the standard ESP32 frozen modules, then add the recovery supervisor.
include("$(PORT_DIR)/boards/manifest.py")

module("main.py", base_path="..", opt=3)
module("core_metadata.py", base_path="$(CORE_METADATA_DIR)", opt=3)
module("recovery_boot.py", base_path="..", opt=3)
module("app_update.py", base_path="..", opt=3)
module("firmware_update.py", base_path="..", opt=3)
module("hardware_platform.py", base_path="..", opt=3)
module("device_config.py", base_path="..", opt=3)
module("portal_ui.py", base_path="..", opt=3)
module("update_security.py", base_path="..", opt=3)
module("credential_security.py", base_path="..", opt=3)
module("credential_store.py", base_path="..", opt=3)
module("factory_config.py", base_path="..", opt=3)
module("setup_wizard.py", base_path="..", opt=3)
module("release_update.py", base_path="..", opt=3)
module("certificate_manager.py", base_path="..", opt=3)
module("update_support.py", base_path="..", opt=3)
module("wifi_recovery.py", base_path="..", opt=3)
module("http_support.py", base_path="..", opt=3)
