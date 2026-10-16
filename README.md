# rsynth-nvda

**RSynth**, Nick Ing-Simmons' formant speech synthesizer (1994–2004), as a
native 64-bit library and an NVDA add-on.

The engine is his C, built as `rsynth.dll` (or `librsynth.so`) with a small
public API around it. The CMU Pronouncing Dictionary is compiled into the
library; words it lacks go through the NRL letter-to-sound rules, as they
always did. The NVDA add-on is one Python file that drives the DLL through
ctypes, and the DLL. A desktop GUI, `rsynth_gui.exe`, exposes every
setting the engine has, with standard Win32 controls that NVDA reads.

Nick Ing-Simmons' own README is [`README`](README); it describes the
original package, its components and their sources.

## Status

| Part | State |
|---|---|
| Library (`rsynth.dll`) | Working. Builds with MSVC (Windows x64) and gcc (Linux); tests pass on both with identical output, and clean under ASan, UBSan and valgrind. |
| `rsynth_say` (text → WAV) | Working. |
| NVDA add-on 3.0.0 | Built; tested against stand-in NVDA modules and in one scripted run inside NVDA 2026.3 (every step ran, 0 errors). Not yet used for everyday reading. |
| GUI (`rsynth_gui.exe`) | Working, Windows only. C++17 over plain Win32, the engine linked in: one 64-bit exe. Checked from outside through MSAA, NVDA's grouping rule, real keystrokes and a WAV compared with `rsynth_say` (93 checks); not yet used by a person with NVDA. A stand-in until Tawkative's single-engine build exists ([docs/07](docs/07-gui.md)). |
| Listening comparison with the original `say` | Not done. |

The earlier pure-Python port, its wxPython GUI included, is kept,
unchanged, on the branch **`python-port`**. See
[docs/01](docs/01-branches-and-provenance.md).

## Building

Needs CMake 3.20+ and a C17 compiler. 64-bit only.

```sh
cmake -S . -B build/msvc -A x64          # Windows, Visual Studio
cmake --build build/msvc --config Release
ctest --test-dir build/msvc -C Release   # C tests, golden hashes included
```

On Linux: `cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release`, then
the same. The GUI is built on Windows only, as
`build/msvc/gui/Release/rsynth_gui.exe`; it needs nothing beside it. Its
outside check (Python with comtypes):

```sh
python tests/gui_check.py build/msvc/gui/Release/rsynth_gui.exe build/msvc/Release/rsynth_say.exe
```

The NVDA add-on:

```sh
python nvda-addon/package.py             # build, test, zip
python tests/test_driver.py              # the driver, without NVDA
```

That writes `nvda-addon/rsynth-<version>.nvda-addon`.

## Using it

**The GUI:** type text, press Ctrl+Enter to speak and Esc to stop, and
Ctrl+S to save a WAV. Ctrl+P shows the normalized text and the phonemes,
and Ctrl+U puts the phonemes in the text box to edit by hand. Every
parameter is a labelled number field: Up and Down step it, Page Up and
Page Down step it ten times. Voices save and load as small text files. F1
lists the keys; NVDA+End reads the status bar, which explains the focused
control.

**The command line:**

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
| `gui/` | The desktop GUI (Windows). |
| `tests/` | C tests with golden hashes, against the DLL and the static library; the driver test; the GUI check. |
| `nvda-addon/` | Driver, manifest, packager. |
| `docs/` | How each stage was done and checked, numbered. |

## Documents

1. [Branches and provenance](docs/01-branches-and-provenance.md)
2. [The library build and every change to the original](docs/02-library-build.md)
3. [The dictionary](docs/03-dictionary.md)
4. [The front end](docs/04-front-end.md)
5. [The NVDA add-on](docs/05-nvda-driver.md)
6. [Verification](docs/06-verification.md)
7. [The desktop GUI](docs/07-gui.md)

## Licence

The engine is LGPL v2 or later (library files) and GPL v2 or later
(programs), as Nick Ing-Simmons released it: `COPYING.LIB`, `COPYING`.
The CMU dictionary is under CMU's BSD-style licence. Everything is listed
in [NOTICE.md](NOTICE.md).
