#!/usr/bin/env python3
"""Copy the Pico runtime files to a mounted MicroPython filesystem."""

import argparse
import shutil
from pathlib import Path


FILES = (
    "main.py",
    "HA-Device.py",
    "settings_loader.py",
    "device_settings.json",
    "module_settings.json",
    "local_display.py",
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
    parser = argparse.ArgumentParser(description="Deploy project files to a mounted Pico filesystem")
    parser.add_argument("mount", help="Path to mounted Pico filesystem")
    parser.add_argument("--secrets", action="store_true", help="Also copy secrets.py if present")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    mount = Path(args.mount).resolve()
    if not mount.exists():
        raise SystemExit("mount path does not exist: " + str(mount))

    files = list(FILES)
    if args.secrets:
        files.append("secrets.py")

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
