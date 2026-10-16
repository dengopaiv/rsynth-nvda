# rsynth-nvda

**RSynth**, Nick Ing-Simmons' formant speech synthesizer (1994–2004), as a
native 64-bit library and an NVDA add-on.

The engine is his C, built as `rsynth.dll` (or `librsynth.so`) with a small
public API around it. The CMU Pronouncing Dictionary is compiled into the
library; words it lacks go through the NRL letter-to-sound rules, as they
always did. The NVDA add-on is one Python file that drives the DLL through
ctypes, and the DLL.

Nick Ing-Simmons' own README is [`README`](README); it describes the
original package, its components and their sources.

## Status

| Part | State |
|---|---|
| Library (`rsynth.dll`) | Working. Builds with MSVC (Windows x64) and gcc (Linux); tests pass on both with identical output, and clean under ASan, UBSan and valgrind. |
| `rsynth_say` (text → WAV) | Working. |
| NVDA add-on 3.0.0 | Built; tested against stand-in NVDA modules and in one scripted run inside NVDA 2026.3 (every step ran, 0 errors). Not yet used for everyday reading. |
| GUI | None. Planned as Tawkative's single-engine build over a `tawk_engine.h` implementation, per the tree's conventions. |
| Listening comparison with the original `say` | Not done. |

The earlier pure-Python port is kept, unchanged, on the branch
**`python-port`**. See [docs/01](docs/01-branches-and-provenance.md).

## Building

Needs CMake 3.20+ and a C17 compiler. 64-bit only.

```sh
cmake -S . -B build/msvc -A x64          # Windows, Visual Studio
cmake --build build/msvc --config Release
ctest --test-dir build/msvc -C Release   # C tests, golden hashes included
```

On Linux: `cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release`, then
the same.

The NVDA add-on:

```sh
python nvda-addon/package.py             # build, test, zip
python tests/test_driver.py              # the driver, without NVDA
```

That writes `nvda-addon/rsynth-<version>.nvda-addon`.

## Using it

```sh
rsynth_say -o hello.wav "Hello, world."
rsynth_say -p "Schedule a tomato."              # print SAMPA phones
rsynth_say -L br -p "Schedule a tomato."        # British phone mapping
rsynth_say -L rules "Schedule a tomato."        # no dictionary
rsynth_say -n "1,234 people on the 21st"        # what the engine is given
```

Options follow the original `say` where the meaning is the same: `-m`
frame length (rate), `-F` F0, `-S` speed, `-K` smoothing, `-G` gain, `-M`
monotone. The C API is [`include/rsynth_api.h`](include/rsynth_api.h).

## Layout

| Path | What |
|---|---|
| `*.c`, `*.h`, `*.def` (top level) | Nick Ing-Simmons' sources. Five small patches, each marked `rsynth-nvda P<n>`: [docs/02](docs/02-library-build.md). |
| `config/`, `configure.ac`, `Makefile.am`, … | The original autotools build and sound drivers, kept, not used by CMake. |
| `port/` | The library's own code: API, text front end, compiled-in dictionary lookup. |
| `include/rsynth_api.h` | The public header. |
| `tools/mkdicttab.c` | `mkdictdb.c` turned into a CMU → C table compiler. |
| `dict/cmudict/` | The CMU Pronouncing Dictionary and its licence. |
| `cli/rsynth_say.c` | Command line. |
| `tests/` | C tests with golden hashes; the driver test. |
| `nvda-addon/` | Driver, manifest, packager. |
| `docs/` | How each stage was done and checked, numbered. |

## Documents

1. [Branches and provenance](docs/01-branches-and-provenance.md)
2. [The library build and every change to the original](docs/02-library-build.md)
3. [The dictionary](docs/03-dictionary.md)
4. [The front end](docs/04-front-end.md)
5. [The NVDA add-on](docs/05-nvda-driver.md)
6. [Verification](docs/06-verification.md)

## Licence

The engine is LGPL v2 or later (library files) and GPL v2 or later
(programs), as Nick Ing-Simmons released it: `COPYING.LIB`, `COPYING`.
The CMU dictionary is under CMU's BSD-style licence. Everything is listed
in [NOTICE.md](NOTICE.md).
