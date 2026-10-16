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

`C:\git\environment\test-addon.ps1` installs an add-on into a throwaway
NVDA profile, runs NVDA for a while and reports what was spoken. It
terminates the running NVDA while it runs, so it is only run with the
user's go-ahead.

On its own it would load the add-on and leave NVDA on its default synth,
so `tests/nvda_test/` adds a harness: `globalPlugins/rsynthTest.py`, a
test-only global plugin (never shipped) that switches NVDA to RSynth with
`setSynth("rsynth")`, then works through scripted steps and logs every
synth notification with the prefix `RSYNTHTEST`:

1. list voices and variants;
2. `synth.speak()` directly, with indexes 101 and 102;
3. `speakMessage` through the speech manager;
4. a long passage, cancelled after 800 ms, then
5. a short one;
6. rate 80, pitch 70, and a sentence with a number and an ordinal;
7. variant 11025;
8. voice "rules";
9. `speakSpelling("NVDA")`;
10. read the settings back.

```
python tests/nvda_test/make_bundle.py OUTDIR
pwsh -File C:\git\environment\test-addon.ps1 -Addon OUTDIR\rsynth-3.0.0.nvda-addon -Seconds 70
```

#### Run of 2026-10-16, NVDA 2026.3beta5

Evidence: [measurements/nvda-run-2026-10-16.txt](measurements/nvda-run-2026-10-16.txt)
(the harness and driver lines from the log).

- `Loaded synthDriver rsynth`; `setSynth ok=True`; the three voices and
  four variants listed.
- Direct speech, issued at 5.16 s: index 101 at 6.60 s, index 102 at
  8.07 s, done at 8.07 s, i.e. as the audio played rather than when it was
  synthesized (synthesis of both parts takes a few milliseconds).
- Every step ran and the settings read back as set. **0 ERROR or
  CRITICAL lines** in the whole log and no traceback from the add-on (the
  log's tracebacks are NVDA's own start-up debug warnings in a bare
  profile).
- Cancel: the long passage (about 30 s of speech) was cancelled at 18.1 s,
  and the next utterances' index marks arrived from 18.9 s on. NVDA's
  player is serial, so they could not have played if the passage had gone
  on.

What limits it: the rig's NVDA found this session's terminal focused and
read its spinner throughout, so most index marks in the log belong to
that chatter rather than to the steps; and nobody listened to the run.

`lastTestedNVDAVersion` was raised to 2026.3.0 on the strength of it.

Two problems with the rig itself, for `C:\git\environment`: it waits a
fixed 5 s after `--create-portable-silent`, which was not enough here (the
copy appeared about 25 s later, so the first attempt failed); and its
`--check-running` test did not see the running NVDA, so the script would
not have restarted it. NVDA was restarted by hand both times.

### Accessibility

The add-on adds no UI of its own: its settings appear in NVDA's own Voice
settings panel and synth settings ring, as standard NVDA controls with the
labels above. There is nothing custom-drawn to check.
