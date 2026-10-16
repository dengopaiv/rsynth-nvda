# 04 — The front end: what the engine is handed

`port/frontend.c` sits between the caller's UTF-8 and the original
`say_string()`. It exists because the 2004 engine assumed ISO-8859-1 text
typed at a shell, and a screen reader hands it anything. `rs_normalize()`
returns its output, and `rsynth_say -n` prints it.

## Made safe

| Input | Problem in the original | Done here |
|---|---|---|
| Any byte above 0x7F | `charset.c`'s `deaccent()` calls `abort()` on a high byte it does not know; `say.c` reaches it when spelling a token. Inside NVDA that kills the screen reader. | Decode UTF-8; map to ASCII. Nothing above 0x7F reaches the engine. |
| `[` and `]` | `say.c` reads `[...]` as literal SAMPA phones. | Become spaces. The front end uses the syntax itself, for ordinals. In spelling mode they are kept, because they have names ("open bracket"). |
| Digit runs over 9 digits | `say.c` accumulates digits in a `long`: 32 bits on Windows, 64 on Linux, and overflow is undefined. | Read digit by digit: `1234567890` → `1 2 3 4 5 6 7 8 9 0`. Every number the engine sees is below 10⁹ on every platform. |
| Control characters, DEL | No useful name. | Spaces. |
| Malformed UTF-8 | — | Each bad byte becomes one space; decoding always moves on. |

### The ASCII mapping

- U+00C0–U+00FF and U+0100–U+017F (Latin-1 and Latin Extended-A): the
  base letter (`é` → `e`, `ł` → `l`), or a digraph where that is the usual
  transliteration (`ß` → `ss`, `æ` → `ae`, `œ` → `oe`, `þ` → `th`, `Ĳ` →
  `IJ`). `×` and `÷` become spaces.
- Typographic punctuation to ASCII: curly quotes and primes to `'` and
  `"`, guillemets to `"`, the dashes and minus sign to `-`, `…` to `...`,
  `¡` `¿` to `!` `?`.
- Zero-width characters and the soft hyphen are dropped.
- Everything else, including whole scripts, is a space. The engine is
  English; NVDA's symbol processing has already turned the symbols it
  knows into words before the driver sees them.

## Numbers read better

| Input | Original | Now |
|---|---|---|
| `1,234,567` | "one", pause, "two hundred thirty four", pause, "five hundred sixty seven" | `1234567`: "one million two hundred thirty four thousand five hundred sixty seven" (`cardinal()` says "and" only before a remainder under 100). Commas are removed only between a 1–3 digit lead and well-formed groups of exactly three, so `12,34` and `1,2345` are left alone. |
| `21st`, `2nd`, `3rd`, `4th` | "twenty one" then "s t" spelt | The ordinal: the front end asks `english.c`'s own `ordinal()` for the phones and hands them on as `[...]`. Only when the suffix stands alone (`21stcentury` is left as it is). |
| `3.14159` | "three point one four one five nine" | Unchanged: digits after a decimal point are left for `say.c`, which spells them. |
| `-42` | "minus forty two" | Unchanged. |

## Tested

`tests/test_api.c`, `test_frontend()`, pins each row above with an exact
expected string, plus a short-buffer case. `test_bytes()` speaks every
byte value 1–255 (alone and around a letter), normally and spelt, and the
whole printable ASCII set, and requires that none fails. Under ASan and
UBSan ([06](06-verification.md)) none of that touches memory it should
not.
