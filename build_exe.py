"""
Build script for creating RSynth GUI standalone executable.

Usage:
    python build_exe.py

This will create a standalone .exe in the dist/rsynth/ folder,
along with a copy of the _rsynth source module for NVDA addon reuse.
"""

import os
import sys
import subprocess
import shutil

def main():
    # Get the directory of this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    print("Building RSynth GUI executable...")
    print(f"Working directory: {script_dir}")

    # Check for required files
    if not os.path.exists("rsynth_gui.py"):
        print("ERROR: rsynth_gui.py not found!")
        return 1

    if not os.path.exists("_rsynth"):
        print("ERROR: _rsynth directory not found!")
        return 1

    # Clean previous builds
    for folder in ["build", "dist"]:
        if os.path.exists(folder):
            print(f"Cleaning {folder}/...")
            shutil.rmtree(folder)

    # Build command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",              # Single executable
        "--windowed",             # No console window
        "--name", "RSynthGUI",    # Executable name
        "--add-data", "_rsynth;_rsynth",  # Include the _rsynth package
        "rsynth_gui.py"           # Main script
    ]

    print(f"\nRunning: {' '.join(cmd)}\n")

    result = subprocess.run(cmd)

    if result.returncode == 0:
        exe_path = os.path.join(script_dir, "dist", "RSynthGUI.exe")
        if os.path.exists(exe_path):
            # Create organized output structure
            print("\nOrganizing output...")
            rsynth_dir = os.path.join(script_dir, "dist", "rsynth")
            os.makedirs(rsynth_dir, exist_ok=True)

            # Move executable to rsynth folder
            new_exe_path = os.path.join(rsynth_dir, "RSynthGUI.exe")
            shutil.move(exe_path, new_exe_path)

            # Copy _rsynth source folder (for NVDA addon reuse)
            src_rsynth = os.path.join(script_dir, "_rsynth")
            dst_rsynth = os.path.join(rsynth_dir, "_rsynth")
            shutil.copytree(src_rsynth, dst_rsynth,
                          ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))

            size_mb = os.path.getsize(new_exe_path) / (1024 * 1024)
            print(f"\nBuild successful!")
            print(f"Output folder: {rsynth_dir}")
            print(f"  - RSynthGUI.exe ({size_mb:.1f} MB)")
            print(f"  - _rsynth/ (source module for NVDA addon)")
        else:
            print("\nBuild completed but executable not found.")
    else:
        print(f"\nBuild failed with return code {result.returncode}")

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
