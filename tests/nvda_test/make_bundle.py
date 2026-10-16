"""Make a test copy of the add-on with the RSYNTHTEST harness inside.

    python tests/nvda_test/make_bundle.py OUTDIR

Writes OUTDIR/rsynth-<version>.nvda-addon: the released add-on plus
globalPlugins/rsynthTest.py. The file name matters: test-addon.ps1 takes
the add-on's folder name from it. Then:

    pwsh -File C:\\git\\environment\\test-addon.ps1 -Addon OUTDIR\\rsynth-<version>.nvda-addon -Seconds 60

which terminates the running NVDA for the duration -- ask first.
"""

import glob
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def main():
	if len(sys.argv) != 2:
		sys.exit(__doc__)
	out_dir = sys.argv[1]
	addons = sorted(glob.glob(os.path.join(ROOT, "nvda-addon", "rsynth-*.nvda-addon")))
	if not addons:
		sys.exit("no add-on built; run nvda-addon/package.py first")
	src = addons[-1]
	os.makedirs(out_dir, exist_ok=True)
	dst = os.path.join(out_dir, os.path.basename(src))
	with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
		for item in zin.infolist():
			zout.writestr(item, zin.read(item.filename))
		zout.write(os.path.join(HERE, "globalPlugins", "rsynthTest.py"), "globalPlugins/rsynthTest.py")
	print(dst)


if __name__ == "__main__":
	main()
