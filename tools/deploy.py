#!/usr/bin/env python3
"""Copy runtime files to a mounted MicroPython filesystem."""

import argparse
import shutil
from pathlib import Path


FILES = (
    "main.py",
    "recovery_boot.py",
    "app_update.py",
    "firmware_update.py",
    "hardware_platform.py",
    "update_security.py",
    "credential_security.py",
    "credential_store.py",
    "factory_config.py",
    "device_config.py",
    "portal_ui.py",
    "setup_wizard.py",
    "certificate_manager.py",
    "update_support.py",
    "wifi_recovery.py",
    "http_support.py",
    "HA-Device.py",
    "release_update.py",
    "settings_loader.py",
    "component_versions.py",
    "app_settings.json",
    "module_settings.json",
    "display.py",
    "web_portal_ui.py",
    "web_portal.py",
)

DIRS = (
    "device_modules",
    "lib",
)

def copy_file(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print("copied", src, "->", dst)


def copy_tree(src, dst):
    if dst.exists():
        shutil.rmtree(dst)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    shutil.copytree(src, dst, ignore=ignore)
    print("copied", src, "->", dst)


def main():
    parser = argparse.ArgumentParser(description="Deploy project files to a mounted MicroPython filesystem")
    parser.add_argument("mount", help="Path to mounted MicroPython filesystem")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    mount = Path(args.mount).resolve()
    if not mount.exists():
        raise SystemExit("mount path does not exist: " + str(mount))

    files = list(FILES)

    for name in files:
        src = root / name
        if src.exists():
            copy_file(src, mount / name)
        else:
            print("missing", src)

    for name in DIRS:
        copy_tree(root / name, mount / name)


if __name__ == "__main__":
    main()
