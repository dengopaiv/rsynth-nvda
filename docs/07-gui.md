# 07 — The desktop GUI

Written 2026-10-16, when the owner asked for "a C or CPP version of the
rsynth gui", with the Python GUI retired to a separate branch.

## Where the Python GUI went

The wxPython GUI, `rsynth_gui.py`, and its PyInstaller script
`build_exe.py` are on the branch **`python-port`** (`1bb9e46`), with the
rest of the Python port, unchanged. They left `master` in `20f8c28`
([01](01-branches-and-provenance.md)), and nothing on `master` refers to
them. `git ls-files '*.py'` on `master` lists only the NVDA driver (NVDA
loads synth drivers only as Python), the add-on packager and the tests.

The GUI described here replaces it: `gui/rsynth_gui.cpp`, built as
`rsynth_gui.exe`.

### What the Python GUI had that this one does not, and why

The Python GUI drove the Python port's own synthesizer, which had grown
parameters Nick Ing-Simmons' engine never had:

| Python GUI control | In the C engine? |
|---|---|
| Rate, Pitch, Gain, Flat intonation | Yes: frame length, F0, gain, monotone. All here. |
| F4–F6 frequencies and bandwidths, nasal pole and bandwidth, parallel bandwidths | Yes: the fixed fields of `speaker_t`. All here, through a new API (below). |
| F1/F2/F3 offset and scale | **No.** The port scaled the element table's formants; `holmes.c` takes them from `Elements.def` as they are. |
| Jitter, shimmer, flutter | **No.** `opsynth.c`'s voicing source has none. |
| Built-in voice presets | They were combinations of the above, mostly of the controls the engine lacks. Voices are now files the user saves (`.rsv`). |

Adding the missing ones means changing the engine, not the GUI. By the
tree's rules that is an enhancement in C17 with its own documentation and
golden traces, not something to slip in here. It has not been done.

## Why a program of its own, not Tawkative

The tree's convention (2026-09-27) is that an engine's GUI is Tawkative's
single-engine build over a `tawk_engine.h` implementation, not a new
program per project. On 2026-10-16 that build does not exist: Tawkative is
in its phase 1, its header is draft 2 (ABI 0, not frozen), and the
single-engine build is its phase 3, planned for AnnoTuBini and klattsch
first (`tawkative/docs/system-plan.md`). rsynth is not scheduled there.

So this program is a stand-in, asked for by the owner. It is deliberately
small and uses only the public API, so when a Tawkative single-engine build
for rsynth exists it can replace this program the way it is meant to
replace `klattsch_gui.exe`. Whatever this program does that Tawkative does
not should then be added to Tawkative for every engine. In particular:
showing the front end's output, and putting the phonemes back into the
text box to edit.

## What it is

- **C++17 over plain Win32**, one source file. The tree's rule is that
  GUIs are Python or C++; the request allowed C or C++.
- **Standard controls only:** edits, combo boxes, push buttons, a check
  box, edit + up-down pairs, group boxes, a menu bar and a status bar. No
  tab control, no custom drawing. These are what NVDA reads without any
  help from the program.
- **The engine linked in statically** (`rsynth_static`, the same sources
  and flags as `rsynth.dll`), so the program is one 64-bit exe, 2.9 MB with
  the CMU dictionary inside. It imports only Windows DLLs: `COMCTL32`,
  `COMDLG32`, `WINMM`, `KERNEL32`, `USER32` and `GDI32` (`dumpbin
  /dependents`; the C runtime is static).
- **Windows only.** The engine and everything else here build on Linux;
  the GUI is Win32. A portable GUI is what Tawkative (wxWidgets) is for.
- The latest build is kept, git-ignored, as `dist/rsynth_gui.exe`, as
  `wintalker` keeps `dist/WinTalker.exe`.

### The window, top to bottom

| Control | Does | API |
|---|---|---|
| Text to speak | Multi-line edit. Ctrl+Enter speaks the selection if there is one, otherwise all of it. | `rs_speak` |
| Read as | Text · Spelled out, character by character · Phonemes (SAMPA) | `RS_SPEAK_SPELL`, `rs_speak_phones` |
| Lexicon | CMU American · CMU British · letter-to-sound rules only | `rs_set_lexicon` |
| Sample rate (Hz) | 8000, 11025, 16000, 22050 (default, as the add-on), 32000, 44100, 48000 | `rs_create` |
| Speak, Stop, Save as WAV..., Show phonemes, Use phonemes as text | See Keys. | |
| **Prosody and output** group | Frame length (ms) 1–40, default 10 · Duration multiplier 0.1–15, 1 · Base pitch (Hz) 40–400, 133 · Gain (dB) 4–80, 57 · Volume (%) 0–200, 100 · Smoothing 0.01–1, 0.5 · Monotone · Reset voice to defaults | `rs_set_frame_ms`, `_speed`, `_f0`, `_gain_db`, `_volume`, `_smooth`, `_monotone` |
| **Speaker: fixed formants and bandwidths** group | F4, F5, F6 frequency · F4, F5 cascade bandwidth · F4, F5, F6 parallel bandwidth · nasal pole frequency · nasal bandwidth | `rs_set_speaker` (new) |
| Normalized text and phonemes | Read-only edit: what the front end made of the text. | `rs_normalize`, `rs_text_to_phones` |
| Status bar | The focused control's explanation, with range and default, and every result. | |

The ranges and defaults of the speaker group are read from the library at
start-up (`rs_speaker_range`, `rs_get_speaker`), not written into the GUI,
so the two cannot disagree.

### Keys

| Key | Action |
|---|---|
| Ctrl+Enter | Speak (the selection, if any) |
| Esc | Stop (closes an open drop-down list instead, if one is open) |
| Ctrl+S | Save the speech as a WAV file |
| Ctrl+P | Show the normalized text and phonemes (focus moves to them) |
| Ctrl+U | Replace the text with its phonemes and set Read as to Phonemes |
| Ctrl+R | Reset every voice setting |
| Ctrl+O / Ctrl+Shift+S | Open / save a voice file |
| F1 | The key list |
| Up / Down in a number | One step; Page Up / Page Down ten steps |
| Alt+T, A, L, R, S, O, W, P, U, M, D, N | The underlined letter of each main control |

The menus use F, C and H, which no control uses.

### Voice files

Plain text, `.rsv`, one `key value` per line, `#` for comments:
`sample_rate`, `lexicon` (`american`, `british`, `rules`), `monotone`, and
one key per number (`frame_ms`, `speed`, `f0`, `gain_db`,
`volume_percent`, `smooth`, `f4_hz`, `b4_hz`, `f5_hz`, `b5_hz`, `f6_hz`,
`b4p_hz`, `b5p_hz`, `b6p_hz`, `fnp_hz`, `bn_hz`). A key the file leaves
out takes its default; an unknown line is skipped and counted; a value out
of range is clamped and counted. The status bar reports both counts.

## Design decisions, and the reasons

- **Labels name controls by creation order.** MSAA names an edit or combo
  box after the static text created just before it, so every label is
  created immediately before its control, and the unit is in the label
  ("Base pitch (Hz):"). The Tawkative spike's NVDA check (2026-10-12)
  found that a plain slider's value is read without its unit, and a label
  that carries it is read; numbers here are edits, never sliders.
- **Group boxes come before their contents** in creation order. NVDA finds
  a Win32 control's group by walking back through the previous windows to
  the first group box whose rectangle holds it. That is
  `IAccessibleHandler.findGroupboxObject` in NVDA's source
  (`C:\git\environment\nvda-source`), read on 2026-10-16. A group box
  created after its controls would never be announced.
- **No `WS_CLIPSIBLINGS` on controls, no `WS_CLIPCHILDREN` on the window.**
  Both were there in the first build, and a capture of the window showed
  both group boxes **empty**. A control with `WS_CLIPSIBLINGS` clips out
  every sibling above it in z-order, and its group box is above it. With
  that fixed, the group interiors were white, because `WS_CLIPCHILDREN`
  kept the window from painting inside group boxes, which draw only their
  frame. Dialog templates use neither style, and neither does this
  program. `WM_CTLCOLORSTATIC` / `WM_CTLCOLORBTN` give labels and group
  boxes the face colour, as a dialog's default procedure does, from system
  colours so that High Contrast applies. The MSAA check could not see any
  of this; only looking at the window did.
- **No tab control.** In wintalker's GUI, Tab could not reach the controls
  inside a tab control under `IsDialogMessage` (wintalker `docs/01`,
  2026-10-16). Seventeen parameters fit in two groups on one page.
- **The keyboard is handled in the message loop, not by `IsDialogMessage`:**
  - Tab and Shift+Tab move over an explicit list, the focusable controls in
    creation order, and wrap at both ends.
  - Enter presses a focused button and commits a focused number.
  - Esc stops.
  - Alt+letter goes through a table.

  `IsDialogMessage` in a window with a menu bar handles Alt+letter in
  ways that are hard to predict. A multi-line edit claims Tab
  (`DLGC_WANTALLKEYS`), which would trap the focus in the text box. And
  Enter in a one-line edit beeps.
- **Numbers: the edit is the authority.** The up-down only reports clicks
  and arrow keys (`UDN_DELTAPOS`). The program steps the value and writes
  it back, which raises the edit's value-change event, which NVDA reads.
  A typed value is used as soon as it parses and lies in range.
- **A value corrected on leaving the field is announced, not just changed.**
  The first build lost it: `EN_KILLFOCUS` wrote "999 is outside the range;
  set to 400" to the status bar, and the next control's `EN_SETFOCUS`
  replaced it at once with its own help, so a screen-reader user tabbing
  on would never learn the value had changed. Found by `tests/gui_check.py`.
  Now the note goes out instead of the next control's help, and a warning
  beep sounds, because a field that has lost the focus is not re-read by
  the screen reader.
- **Focus comes back where it was** after Alt+Tab or a file dialog
  (`WM_ACTIVATE`), as in a dialog box.
- **Synthesis on a worker thread, from a fresh engine per utterance** built
  from a copy of the settings, so no engine is ever shared between threads.
  The engine renders far faster than real time
  ([06](06-verification.md): about 330×), so the whole utterance goes to
  memory, then to `waveOut` in one-second blocks. Esc cancels the
  synthesis (the callback returns non-zero) and resets the device. Results
  carry a job number; one that arrives after Stop or a newer Speak is
  dropped.
- **Clipping is reported.** Samples at the 16-bit limit after Gain and
  Volume are counted, and the status bar says how many clipped.

## The engine API additions

The GUI needed the speaker parameters, which `rsynth_api.h` did not expose.

- `rs_set_speaker(e, param, value)`, `rs_get_speaker(e, param)` and
  `rs_speaker_range(param, &lo, &hi)` over `enum rs_speaker_param`:
  - F4, F5, F6 frequency;
  - F4, F5 cascade bandwidth;
  - F4, F5, F6 parallel bandwidth;
  - nasal pole frequency, and the nasal pole and zero bandwidth.

  These are the fields of `speaker_t` that `opsynth.c` reads. `B6hz` is in
  the struct, but nothing reads it (only the parallel `B6phz` is used for
  F6), so it is not offered. The ranges are the ones `rsynth.h`'s comments
  give. The defaults are `elements.c`'s `rsynth_speaker()` constants. The
  nasal pole's default comes from element 0's nasal zero, which is 270 Hz.
- The values are kept beside the speaker, and copied into it when each
  `rs_speak*` starts, like F0 and gain. `opsynth.c` reads the speaker on
  every frame, so storing straight into it would let a change from another
  thread land in the middle of an utterance.
- `RSYNTH_STATIC` in the header makes `RSYNTH_EXPORT` empty, for linking
  the static library.
- **`RS_API_VERSION` stays 1.** The header bumps it when an existing
  function's signature or meaning changes, and none did. The NVDA driver
  requires exactly 1. Add-on 3.0.0, as built and tested, has a DLL without
  these functions, and the driver does not use them. The next add-on build
  will carry them, unused.

### How the additions were checked

| Check | Result |
|---|---|
| `tests/golden.txt` unchanged, `test_api` against `rsynth.dll` (MSVC) | passed: the default speaker gives the same samples as before |
| New `test_speaker` in `test_api.c`: each default equals `elements.c`'s; values clamp at both ends; unknown parameters are refused; changing two parameters changes the hash with the same length; restoring them restores the exact hash | passed |
| `test_api_static`, the same checks against the static library the GUI links | passed, same golden hashes |
| gcc 14.2 Release in WSL, both tests | passed, same golden hashes |
| gcc 14.2 with ASan and UBSan, both tests | passed, clean |
| `tests/test_driver.py`, NVDA driver against the new DLL | passed |

## How the GUI was checked

`tests/gui_check.py` drives the built program from outside and reads it
the way a screen reader does. The full output of the recorded run is in
[measurements/gui-check-2026-10-16.txt](measurements/gui-check-2026-10-16.txt):
93 checks, none failed.

```sh
python tests/gui_check.py build/msvc/gui/Release/rsynth_gui.exe build/msvc/Release/rsynth_say.exe
```

1. **MSAA.** These are read through `AccessibleObjectFromWindow` for every
   tab stop: role, name and value. That is the layer NVDA reads for
   standard Win32 controls. All 28 tab stops have the right role and their
   label as their name. Each number field reports its value.
2. **Groups.** Each control's group is found by the same walk as NVDA's
   `findGroupboxObject`. The six prosody numbers, Monotone and Reset fall
   in "Prosody and output". The ten speaker numbers fall in "Speaker:
   fixed formants and bandwidths". Nothing else falls in a group.
3. **Tab order.** Real Tab and Shift+Tab keystrokes are posted, and the
   focus is read back with `GetGUIThreadInfo`. Tab goes through all 28
   controls in creation order and back to the text box. Shift+Tab goes
   from the text box to the last control, then one further back.
4. **Numbers.**
   - Up gives 134, Page Up 144, Down 143, and MSAA reads 143.
   - 999 becomes 400 on leaving the field, and the status says so.
   - "abc" is put back to the last value.
   - Reset gives 133.
5. **Commands.**
   - Alt+L and Alt+T move the focus.
   - Show phonemes gives exactly what `rsynth_say -p` and `-n` give, and
     moves the focus to the output.
   - **Save as WAV through the real file dialog gives the same 150,280
     samples as `rsynth_say`, byte for byte.**
   - A saved voice reloads pitch 180 and Monotone after a Reset.
   - Ctrl+Enter speaks, at volume 0, and playback finishes.
   - Esc stops a long utterance, and nothing finishes after it.
   - Esc with nothing playing says so.
   - WM_CLOSE exits with code 0.

**Isolation, and the two failures that led to it.** The machine the check
runs on is the owner's, with NVDA running. The first version started the
window minimised or shown inactive, on the owner's desktop:

- Minimised, the window has no focused control, so the Tab checks failed.
  That is an artefact of the check, not of the program.
- Shown inactive, two runs out of eleven failed differently:
  - once every posted Tab stayed in the text box;
  - once Ctrl+Enter and a focus move did nothing.

  The window is reachable by the owner's own keystrokes and window
  switching, and the program reads modifier state with `GetKeyState`: a
  Ctrl held by the owner (NVDA users press it to silence speech) turns a
  posted Tab into Ctrl+Tab, which rightly does not move the focus. This is
  inferred from the symptoms; the owner's input was not observed.

The check now:

- creates its own desktop (`CreateDesktop`), starts the GUI there through
  `CreateProcessW` with `lpDesktop`, and moves its own thread there before
  COM starts. Nothing the owner does can reach the GUI, and NVDA never sees
  it.
- sets the exact state of Shift, Ctrl and Alt for every key it posts.
- waits with `WaitForInputIdle`, because a SendMessage round trip can
  return while posted keys are still queued.

On the private desktop, all 19 runs passed. They span the later changes
(the painting fixes, the group check). The very first run, minimised on the
owner's desktop, also showed the status changing within half a second of
"Stopped.". That never recurred, and its cause was not established.

**Looking at it.** The window was rendered with `PrintWindow` on the
private desktop at 120 dpi (1075 × 975 pixels), and the image was looked
at. That is how the empty group boxes and the colour fault were found and
then seen fixed. The final picture: both groups filled, labels left and
fields right in even columns, nothing clipped. The capture is not kept in
the repository.

## Not yet verified

- **A person using it with NVDA.** Everything above is what NVDA *would*
  read, established through MSAA and NVDA's own grouping rule. Nobody has
  yet tabbed through it with NVDA speaking, heard the value changes on
  Up/Down, or used it to make a sound they wanted. (The tree's rules ask
  for that check.)
- **By ear.** Speaking was checked at volume 0. That the parameters do
  what their names say was established from the engine source, and from
  the test that a change changes the samples, not by listening.
- Other DPI settings than 120, and High Contrast, have not been looked at.
