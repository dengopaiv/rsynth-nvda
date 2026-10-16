# 05 — The NVDA add-on

## Shape

```
rsynth-3.0.0.nvda-addon
  manifest.ini
  synthDrivers/rsynth.py     the driver: Python, ctypes only
  synthDrivers/rsynth.dll    the whole synthesizer, x64
  NOTICE.md, COPYING.LIB.txt, LICENSE-cmudict.txt
```

About 1 MB. No Python package, no data file, no dictionary file, no
32-bit anything: `minimumNVDAVersion` is 2026.1, the first 64-bit-only
NVDA, and `check()` also refuses a 32-bit interpreter. The DLL links the
C runtime statically, so it needs nothing installed.

`python nvda-addon/package.py` configures and builds with CMake (x64,
Release, in `build/addon-x64`), runs the C tests and refuses to package
if they fail, checks that the DLL's PE header says x64 or ARM64, checks
`manifest.ini` the way NVDA will read it, and zips.

## The driver

`nvda-addon/addon/synthDrivers/rsynth.py`. Modelled on Votraxxion's
`votraxNative.py` and on NVDA's own eSpeak and OneCore drivers
(`nvda-source/source/synthDrivers/`).

- **One speak thread.** `speak()` only turns the speech sequence into
  queue items; the thread is the only code that calls the engine or feeds
  the player after start-up.
- **Index marks** are queued in place and, on the thread, attached to the
  player with `feed(b"", onDone=...)`, so NVDA hears about an index when
  the audio before it has played, not when it was synthesized. This is
  what `_espeak.py` does when an index falls on a block boundary.
- **Cancel** bumps an epoch. Queued items from older epochs are dropped;
  settings items carry no epoch and survive. The audio callback returns 1
  the moment it sees the epoch move, and the library then stops at the
  next element (patch P3). A block fed while `cancel()` was running is
  stopped again, so it cannot sound at the head of the next utterance.
- **Settings** are recorded on NVDA's thread and applied on the speak
  thread between utterances, because the library's setters are plain
  stores and its lock is held for a whole utterance.

| NVDA setting | Library | Mapping |
|---|---|---|
| Voice | `rs_set_lexicon` | American (CMU) · British phones (CMU) · Letter-to-sound rules only. See [03](03-dictionary.md). |
| Variant | sample rate (new engine + player) | 22 kHz (default) · 16 kHz · 11 kHz (the original's Linux default) · 8 kHz (its default elsewhere) |
| Rate 0–100 | `rs_set_frame_ms` | Speed factor 0.5 at 0, 1.25 at 50, 4.0 at 100, exponential in each half; frame = 10 ms ÷ factor. The original speed (factor 1) is near rate 38. |
| Pitch 0–100 | `rs_set_f0` | 133 Hz × 2^((p − 50) / 50): an octave either side of the original 133 Hz. |
| Volume 0–100 | `rs_set_volume` | Linear, 1.3 at 100 ([02](02-library-build.md), "Peaks"). |
| Monotone | `rs_set_monotone` | The original `-M`. |

Commands: `IndexCommand`, `CharacterModeCommand` (spelling through
`english.c`'s character names), `BreakCommand` (silence fed to the player)
and `PitchCommand` (capital-letter pitch, applied to the text it covers).

## Tests

### Without NVDA: `tests/test_driver.py`

Loads the real driver file with stand-ins for the NVDA modules it
imports, against the real `rsynth.dll` (`package.py` copies it beside the
driver). It checks:

1. index marks are attached after the audio before them and before the
   audio after them, values in order, then exactly one "done";
2. a cancel during a long utterance: at most one block fed after the last
   `stop()`, no "done" for the cancelled utterance, synthesis did stop;
3. a rate change followed at once by a cancel still takes effect;
4. a variant change reopens the player at the new rate;
5. every voice, a pitch command around spelling, a 500 ms break, monotone
   and volume all produce audio and stick;
6. CJK text, an emoji, brackets, a 20-digit number and control characters
   produce no error.

Result 2026-10-16: all passed.

What it cannot show: NVDA's real player, its speech manager, its settings
dialogs, how it behaves with a screen reader actually using it.

### In NVDA

`C:\git\environment\test-addon.ps1` installs the add-on into a throwaway
NVDA profile and records what was spoken. It terminates the running NVDA
while it runs, so it is only run with the user's go-ahead.

Status: **not yet run.** `lastTestedNVDAVersion` stays at 2026.1.0 until
it has been, and is raised to the version it ran on.

### Accessibility

The add-on adds no UI of its own: its settings appear in NVDA's own Voice
settings panel and synth settings ring, as standard NVDA controls with the
labels above. There is nothing custom-drawn to check.
