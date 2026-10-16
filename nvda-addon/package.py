#!/usr/bin/env python3
"""Build the RSynth NVDA add-on.

    python nvda-addon/package.py [--skip-tests]

1. Configures and builds the library with CMake, 64-bit, Release, into
   build/addon-x64 (Visual Studio on Windows, whatever CMake picks
   elsewhere -- but the add-on itself only makes sense on Windows).
2. Runs the C tests (tests/test_api.c), golden hashes included, unless
   --skip-tests: an add-on whose engine fails them is not shipped.
3. Zips manifest.ini, the driver, rsynth.dll and the licence files into
   nvda-addon/rsynth-<version>.nvda-addon.

There is no 32-bit build and no x86 DLL: NVDA 2026 is 64-bit only, and
nothing here produces 32-bit artefacts.
"""

import os
import shutil
import subprocess
import sys
import zipfile

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(ADDON_DIR)
BUILD = os.path.join(ROOT, "build", "addon-x64")
DRIVER = os.path.join(ADDON_DIR, "addon", "synthDrivers", "rsynth.py")

#: Files from the repository that go into the add-on, and where.
LICENCE_FILES = (
	(os.path.join(ROOT, "NOTICE.md"), "NOTICE.md"),
	(os.path.join(ROOT, "COPYING.LIB"), "COPYING.LIB.txt"),
	(os.path.join(ROOT, "dict", "cmudict", "LICENSE"), "LICENSE-cmudict.txt"),
)

MANIFEST_REQUIRED = ("name", "summary", "author", "version", "minimumNVDAVersion", "lastTestedNVDAVersion")


def run(cmd, **kw):
	print("+", " ".join(f'"{c}"' if " " in c else c for c in cmd))
	subprocess.run(cmd, check=True, **kw)


def read_manifest():
	"""Parse manifest.ini as NVDA's ConfigObj would, and refuse what NVDA
	would reject without saying why: a [section] header (NVDA's keys are
	top level), an unquoted value with a comma (read as a list), a missing
	required key."""
	values, errors = {}, []
	with open(os.path.join(ADDON_DIR, "manifest.ini"), encoding="utf-8") as f:
		for number, line in enumerate(f, 1):
			line = line.strip()
			if not line or line.startswith("#"):
				continue
			if line.startswith("["):
				errors.append(f"line {number}: sections are not allowed")
				continue
			key, _, value = line.partition("=")
			key, value = key.strip(), value.strip()
			if "," in value and value[:1] not in ('"', "'"):
				errors.append(f"line {number}: {key} has a comma and is not quoted")
			values[key] = value.strip('"').strip("'")
	missing = [k for k in MANIFEST_REQUIRED if not values.get(k)]
	if missing:
		errors.append(f"missing keys: {', '.join(missing)}")
	if errors:
		sys.exit("manifest.ini would be rejected by NVDA:\n  " + "\n  ".join(errors))
	return values


def build():
	gen = []
	if os.name == "nt":
		gen = ["-A", "x64"]
	run(["cmake", "-S", ROOT, "-B", BUILD, *gen])
	run(["cmake", "--build", BUILD, "--config", "Release"])


def test():
	run(["ctest", "--test-dir", BUILD, "-C", "Release", "--output-on-failure"])


def find_dll():
	for sub in ("Release", ""):
		for name in ("rsynth.dll", "librsynth.so"):
			path = os.path.join(BUILD, sub, name)
			if os.path.isfile(path):
				return path
	sys.exit(f"no rsynth library under {BUILD}")


def is_pe64(path):
	"""True when the DLL is x64 or ARM64: check the PE machine field rather
	than trusting the build directory's name."""
	with open(path, "rb") as f:
		data = f.read(4096)
	if data[:2] != b"MZ":
		return False
	pe = int.from_bytes(data[0x3C:0x40], "little")
	machine = int.from_bytes(data[pe + 4 : pe + 6], "little")
	return data[pe : pe + 4] == b"PE\0\0" and machine in (0x8664, 0xAA64)


def package(version, dll):
	if not is_pe64(dll):
		sys.exit(f"{dll} is not a 64-bit Windows DLL")
	out = os.path.join(ADDON_DIR, f"rsynth-{version}.nvda-addon")
	if os.path.exists(out):
		os.remove(out)
	with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
		z.write(os.path.join(ADDON_DIR, "manifest.ini"), "manifest.ini")
		z.write(DRIVER, "synthDrivers/rsynth.py")
		z.write(dll, "synthDrivers/rsynth.dll")
		for src, arc in LICENCE_FILES:
			z.write(src, arc)
	with zipfile.ZipFile(out) as z:
		names = z.namelist()
	print(f"\n{os.path.relpath(out, ROOT)} ({os.path.getsize(out) // 1024} KB)")
	for name in names:
		print("  " + name)
	return out


def main():
	manifest = read_manifest()
	build()
	if "--skip-tests" not in sys.argv:
		test()
	dll = find_dll()
	# Keep a copy beside the driver so tests/test_driver.py and a hand-made
	# install can find it; it is ignored by git.
	shutil.copy2(dll, os.path.join(os.path.dirname(DRIVER), "rsynth.dll"))
	package(manifest["version"], dll)


if __name__ == "__main__":
	main()
