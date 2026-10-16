# 02 — The library build, and every change to the original sources

## What is built

`CMakeLists.txt` builds four things, all 64-bit (configuring a 32-bit
target is a hard error):

| Target | What |
|---|---|
| `rsynth` | `rsynth.dll` / `librsynth.so`: the engine plus `port/`. |
| `mkdicttab` | Host tool, run during the build: CMU dictionary → C table ([03](03-dictionary.md)). |
| `rsynth_say` | Command line: text → WAV, over the public API only. |
| `test_api` | The C tests ([06](06-verification.md)). |

The engine sources are exactly the `COMMON_SOURCES` that `Makefile.am`
gives `say`, minus `deutsch.c`:

```
opsynth.c elements.c holmes.c trie.c phtoelm.c darray.c
say.c phones.c text.c english.c charset.c
```

Left out, and why:

| File | Why not |
|---|---|
| `config/*play.c`, `hplay.c`, `naplay.c` | Sound card drivers. The library hands audio to its caller. |
| `aufile.c`, `l2u.c` | `.au`/`.wav` writing via libsndfile. `rsynth_say` writes its own WAV. |
| `getarg.c`, `saymain.c`, `Revision.c` | The `say` program. `port/rsynth_api.c` takes `saymain.c`'s place. |
| `dict.c`, `dbif.h`, `mkdictdb.c`, `dlookup.c` | GDBM / Berkeley DB dictionary. Replaced by a compiled-in table. |
| `deutsch.c` | German rules. The library is English; German is a possible later voice. |
| `guess.c` | Not in any target of the original build either. |

`port/config.h` stands in for the autoconf `config.h`. It defines
`STDC_HEADERS`, `HAVE_LIMITS_H`, `HAVE_UNISTD_H` off Windows, and
`RSYNTH_LIBRARY`, which the patches below key on.

MSVC reads the sources as code page 1252 (`/source-charset:.1252
/execution-charset:.1252`): `english.c` and `charset.c` hold ISO-8859-1
byte literals, and 1252 agrees with ISO-8859-1 on every byte they use.
The CRT is linked statically, so the DLL needs nothing installed.

### Build output

MSVC 14.51 (VS 2026), `/W3`, Release: one warning, C4477 in `phtoelm.c`
`rsynth_pho()`: `%.*s` is given a pointer difference, which is 64 bits on
x64. It is wrong on any 64-bit target, but `rsynth_pho()` reads MBROLA
`.pho` files and is not reachable from the library's API, so it is left as
it was and recorded here.

gcc 14.2 (WSL Debian), default flags: no warnings.

## The patches

Each is marked in the source with `rsynth-nvda P<n>`. P2, P4 and P5 take
effect only when `RSYNTH_LIBRARY` is defined; P3 adds a flag that nothing in
the original programs sets; P1 fixes undefined behaviour and changes no
defined output. A `say` built from these sources behaves as before. `git diff 6111065 --
'*.c' '*.h'` shows all of them.

| # | File | Change | Why, and how it was found |
|---|---|---|---|
| P1 | `holmes.c` | `float contour[3]` → `= { 0, 0, 0 }` | `rsynth_interpolate()` builds a default F0 contour with `f0[1] += elm[i + 1]`, summing into an uninitialised float. Found by reading. It is reached only with `RSYNTH_MONOTONE` (otherwise `phone_to_elm()` always supplies at least three F0 values), so monotone speech had a stack-garbage F0 timeline. |
| P2 | `holmes.c` | `CHECK_SPACING` compiles to nothing | It `fprintf`s to **stdout** whenever two formants come within 200 Hz, which happens in ordinary speech. A library inside NVDA must not write to stdout. |
| P3 | `rsynth.h`, `holmes.c`, `say.c` | New flag `RSYNTH_STOP`; the element loop in `rsynth_interpolate()` and the word loop in `_xlate_string()` end when it is set | Cancelling. The API sets it when the host's audio callback asks to stop, so synthesis ends at the next element instead of running to the end of the text. Without it a cancelled paragraph would still be synthesized (and discarded) in full. |
| P4 | `say.c` | The "Spelling …", per-letter and "Guess …" messages to stderr are compiled out | Same reason as P2. (They were guarded by `#ifndef DEBUG`, i.e. printed in normal builds.) |
| P5 | `opsynth.c` | `gen_noise()`: the 14-bit sign extension done by `(long) seed << (bits - 32) >> (bits - 14)` is replaced by `(seed >> 18)`, minus 16384 when ≥ 8192 | **Found by UBSan** under WSL: `opsynth.c:381: left shift of 2210330528 by 32 places cannot be represented in type 'long int'`. Where `long` is 64 bits the shift goes into the sign bit, which is undefined. Where it is 32 bits (Windows) the shift is by 0 and the conversion is merely implementation-defined. The replacement is the same arithmetic without either. The golden hashes did not move, on MSVC or gcc. |

Nothing else in the original sources was changed. In particular
`charset.c`'s `deaccent()`, which calls `abort()` on any byte above 0x7F it
does not recognise, is left alone: the front end
([04](04-front-end.md)) guarantees no such byte reaches it.

## What `port/` adds

| File | Role |
|---|---|
| `port/rsynth_api.c` | The public functions (`include/rsynth_api.h`). Plays `saymain.c`'s part: picks English, sets up a speaker, gives `rsynth_init()` a sample and a flush handler, calls `say_string()`. |
| `port/frontend.c` | UTF-8 → the ASCII the engine can take; numbers ([04](04-front-end.md)). |
| `port/dict_builtin.c` | `dict.c`'s lookup over the compiled-in table ([03](03-dictionary.md)). |
| `include/rsynth_api.h` | The only header a host needs. |

### Behaviour worth knowing

- **Fresh synthesizer per call.** Each `rs_speak*` call starts from a new
  `rsynth_init()`: same noise seed (5), zeroed filters. Output depends only
  on the text and the settings. `say` carried filter state across
  utterances; every utterance ends on silence, so nothing audible is lost.
- **Rate is the frame length.** Every duration in the engine — element
  lengths, transition lengths, the F0 contour — is counted in frames of
  `samples_frame` samples. `rs_set_frame_ms()` sets that directly, so 5 ms
  is exactly twice as fast as the original 10 ms with every element kept.
  The original `-S` speed multiplier is there too (`rs_set_speed()`), but it
  rounds each element to whole frames, so values well below 1 drop short
  elements entirely, as they always did.
- **Element durations live in a byte** (`phtoelm.c` stores them in a
  `char` darray). The longest element is 16 frames, so `rs_set_speed()` is
  clamped to 15.
- **Global state, one lock.** The phone trie (which `trie_lookup()`
  reorders on every lookup), the language and the dialect are globals. One
  process-wide lock serialises every call that touches them. Setters do not
  take it (it is held for whole utterances), so they are plain stores, read
  at the next `rs_speak*`.
- **Peaks.** At the default gain (57 dB) and volume 1.0 the loudest sample
  seen so far is 21,659 of 32,767 (a one-hour run of repeated mixed text;
  a five-second sentence peaked at 19,493). The NVDA driver's volume 100 is
  a scale of 1.3, which puts that peak near 28,000. Samples beyond the
  16-bit range are clipped, as `saymain.c` clipped them.
