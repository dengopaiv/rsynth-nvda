"""
Build script for creating RSynth NVDA addon package.

Usage:
    python build_addon.py

This will:
1. Copy the latest _rsynth source into the addon's synthDrivers/_rsynth/
2. Package everything into dist/rsynth-<version>.nvda-addon
"""

import configparser
import os
import shutil
import sys
import zipfile


# Files to copy from _rsynth/ source into the addon
RSYNTH_FILES = [
    "__init__.py",
    "klatt.py",
    "phonemes.py",
    "elements.py",
    "text2phone.py",
    "english_rules.py",
    "cmudict.py",
    "cmudict.txt",
    "espeak_fallback.py",
    "phoneme_rules.py",
]


def read_version(manifest_path):
    """Read addon version from manifest.ini."""
    config = configparser.ConfigParser()
    # manifest.ini has no section headers, so prepend a dummy section
    with open(manifest_path, "r") as f:
        content = "[addon]\n" + f.read()
    config.read_string(content)
    return config.get("addon", "version")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    addon_dir = os.path.join(script_dir, "rsynth-nvda")
    source_dir = os.path.join(script_dir, "_rsynth")
    manifest_path = os.path.join(addon_dir, "manifest.ini")

    # Validate required paths
    for path, label in [
        (addon_dir, "rsynth-nvda/"),
        (source_dir, "_rsynth/"),
        (manifest_path, "rsynth-nvda/manifest.ini"),
    ]:
        if not os.path.exists(path):
            print(f"ERROR: {label} not found!")
            return 1

    version = read_version(manifest_path)
    print(f"Building RSynth NVDA addon v{version}...")

    # Copy latest _rsynth source into addon
    dest_rsynth = os.path.join(addon_dir, "synthDrivers", "_rsynth")
    os.makedirs(dest_rsynth, exist_ok=True)

    print("Copying latest _rsynth source files...")
    copied = 0
    for filename in RSYNTH_FILES:
        src = os.path.join(source_dir, filename)
        if not os.path.exists(src):
            print(f"  WARNING: {filename} not found in _rsynth/, skipping")
            continue
        shutil.copy2(src, os.path.join(dest_rsynth, filename))
        copied += 1
    print(f"  Copied {copied} files")

    # Clean out stale files from dest that aren't in our list
    for filename in os.listdir(dest_rsynth):
        if filename in RSYNTH_FILES:
            continue
        if filename == "__pycache__" or filename.endswith((".pyc", ".pyd")):
            path = os.path.join(dest_rsynth, filename)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            print(f"  Removed stale: {filename}")

    # Create output directory
    dist_dir = os.path.join(script_dir, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    output_path = os.path.join(dist_dir, f"rsynth-{version}.nvda-addon")

    # Package as ZIP with .nvda-addon extension
    print(f"Packaging addon...")
    file_count = 0
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(addon_dir):
            # Skip unwanted directories
            dirs[:] = [d for d in dirs if d != "__pycache__" and d != "_klatt_c"]
            for filename in files:
                if filename.endswith((".pyc", ".pyd")):
                    continue
                full_path = os.path.join(root, filename)
                arc_name = os.path.relpath(full_path, addon_dir)
                zf.write(full_path, arc_name)
                file_count += 1

    size_kb = os.path.getsize(output_path) / 1024
    print(f"\nBuild successful!")
    print(f"  Output: {output_path}")
    print(f"  Files:  {file_count}")
    print(f"  Size:   {size_kb:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
