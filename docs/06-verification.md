# 06 — Verification

## What "correct" means here

There is no frozen reference implementation to compare against other than
the engine itself: the C sources *are* the reference, and the library runs
them. So verification has two parts:

- **Nothing in the wrapping changes the engine's output** beyond what is
  documented. The patches either compile out diagnostics, add a stop flag
  nothing sets during a normal run, or replace undefined arithmetic with
  defined arithmetic giving the same values ([02](02-library-build.md)).
- **The output is pinned** from here on, so any later change is seen.
  `tests/golden.txt` records, for fifteen corpus items, the sample count
  and FNV-1a 64 hash of the PCM. They were recorded from this library on
  2026-10-16. Updating them (`test_api golden.txt --update`) is a
  deliberate act that has to be explained in these documents.

## The runs, 2026-10-16

| Build | Where | Result |
|---|---|---|
| MSVC 14.51, x64, Release | Windows, `build/msvc` and `build/addon-x64` | all passed |
| gcc 14.2, Release (-O2) | WSL Debian 13, `/tmp` | all passed, **golden hashes identical to MSVC** |
| gcc 14.2, `-fsanitize=address,undefined -fno-sanitize-recover=undefined -O1`, leak detection on | WSL | all passed after patch P5 (the first run stopped on the `gen_noise()` shift UBSan reported) |
| gcc 14.2, -O0, under `valgrind --track-origins=yes --leak-check=full` | WSL | no errors, golden identical |
| `tests/test_driver.py` against the MSVC DLL | Windows, Python 3.13.15 | all passed |
| The add-on inside NVDA 2026.3beta5, `tests/nvda_test` harness | Windows, throwaway profile | every step ran, 0 errors; see [05](05-nvda-driver.md) |

That the golden hashes agree between MSVC on Windows and gcc on Linux, at
-O0 and -O2, says the engine's float arithmetic is reproducible across
these compilers (both use SSE2 scalar floats on x86-64, and the library
functions it calls — `exp`, `cos`, `pow` — agree on the values it feeds
them). It is an observation, not a guarantee for other compilers or
architectures.

To repeat the WSL runs (from Windows; the rules in
`C:\git\environment\TOOLCHAIN.md` apply: build in `/tmp`, no git in WSL):

```sh
MSYS_NO_PATHCONV=1 wsl.exe -d Debian -- sh -c '
  rm -rf /tmp/rsynth && mkdir -p /tmp/rsynth &&
  cd "/mnt/c/GIT/speech synthesis/rsynth" &&
  tar --exclude=./build --exclude=./_rsynth --exclude=./dist --exclude=./.git -cf - . |
    tar -C /tmp/rsynth -xf - &&
  cd /tmp/rsynth &&
  cmake -S . -B asan -G Ninja -DCMAKE_BUILD_TYPE=Debug \
    -DCMAKE_C_FLAGS="-fsanitize=address,undefined -fno-sanitize-recover=undefined -g -O1" \
    -DCMAKE_EXE_LINKER_FLAGS="-fsanitize=address,undefined" \
    -DCMAKE_SHARED_LINKER_FLAGS="-fsanitize=address,undefined" &&
  cmake --build asan && ./asan/tests/test_api tests/golden.txt'
```

WSL's `/tmp` is emptied when the distro shuts down after idling, so do the
copy, the build and the run in one invocation.

## Speed

`rsynth_say` on 400 repetitions of a 16-word sentence with numbers
(3708 s of audio at 22050 Hz, written to a 163 MB WAV): 11.3 s wall
clock, about 330 times real time, WAV writing included. The whole
`test_api` suite runs in under a second. Synthesis time is therefore
never what limits how fast a cancel is heard; the audio block (1024
samples, 46 ms at 22 kHz) is.

## Not yet verified

- **Daily use in NVDA.** One scripted run ([05](05-nvda-driver.md)) is
  not reading with it: navigation, say-all, typing echo and the settings
  ring by hand are still to be tried.
- **By ear.** Nobody has listened to this build yet. The golden hashes
  prove it is stable, not that it sounds like `say` did; a listening
  comparison with an autotools `say` built in WSL from the same sources
  would settle that, and is the natural next check.
- ARM64 Windows: the build allows it; nothing has been built or run there.
