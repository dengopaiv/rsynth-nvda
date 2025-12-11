#!/usr/bin/env python3
"""Build script for RSynth NVDA addon."""
import os
import zipfile

ADDON_DIR = "addon"
OUTPUT_FILE = "rsynth.nvda-addon"


def build_addon():
    """Create .nvda-addon package from addon directory."""
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    addon_path = os.path.join(script_dir, ADDON_DIR)
    output_path = os.path.join(script_dir, OUTPUT_FILE)

    if not os.path.isdir(addon_path):
        print(f"Error: {ADDON_DIR}/ directory not found")
        return 1

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(addon_path):
            # Skip __pycache__ directories
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for file in files:
                # Skip compiled Python files
                if file.endswith('.pyc'):
                    continue
                filepath = os.path.join(root, file)
                # Use forward slashes for zip paths (required by NVDA)
                arcname = os.path.relpath(filepath, addon_path).replace('\\', '/')
                zf.write(filepath, arcname)
                print(f"  Added: {arcname}")

    print(f"\nCreated {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    exit(build_addon())
