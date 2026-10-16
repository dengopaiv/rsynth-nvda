# 03 — The dictionary

## What the original did

`say` looked words up in a GDBM (or Berkeley DB) file, `aDict.db` or
`bDict.db`, built beforehand by `mkdictdb` from the CMU Pronouncing
Dictionary or from BEEP. Each record mapped a lower-case word to a string
of phone codes: the 1-based position of each phone in `phones.def`. At
synthesis time `say.c`'s `xlate_word()` turned the codes into SAMPA
through one of two columns of `phones.def`, `ph_am` or `ph_br`, chosen by
`dict.c`'s `choose_dialect()`: look up "wash"; if it starts W OH it is
British, if W AA1, American. Words not found went to the NRL rules.

## What this build does

The same, with the database file replaced by a table compiled into the
library:

1. `tools/mkdicttab.c` is `mkdictdb.c` with the database calls replaced by
   an in-memory store. Its parsing loop is `mkdictdb.c`'s, kept line for
   line so the two can be compared; changes are marked `mkdicttab:`.
   It links the original `trie.c` and `phones.c`, so the arpabet → code
   mapping is the original's own trie over `ph_name`.
2. CMake runs it during the build on `dict/cmudict/cmudict.dict` and
   compiles the output, `cmudict_table.c`, into the library.
3. `port/dict_builtin.c` binary-searches the table and returns a malloc'd
   code string, which is what `dict.c`'s `dict_lookup()` returned, so
   `xlate_word()` is unchanged.

The table is one byte array (`word NUL codes NUL` per entry) and an array
of offsets. It is emitted as numbers, not string literals, because MSVC
caps a string literal at 64 KB.

### mkdicttab's changes to mkdictdb's rules

| mkdictdb | mkdicttab | Effect on CMU |
|---|---|---|
| Folds BEEP's accent escapes (`"a`, `~n`, `\'e`) into ISO-8859-1 letters | Refuses a word containing one | None: CMU has none. Keeps the table pure ASCII. |
| `(unsigned) trie_lookup(...)` | Same via `intptr_t` | None; the original cast truncates a pointer on 64-bit. |
| `DB_STORE` with `GDBM_INSERT` keeps the first record for a key | Sort by (word, source line), keep the first | None: no duplicate keys in this CMU (0 dropped). |

### The run

From the build log, cmusphinx/cmudict at `74790861f652b15e4ac49015a90074ad62a27690`:

```
mkdicttab: 126052 words, 0 duplicate keys dropped, 9114 lines ignored,
           0 with bad codes, 1996348 bytes
```

The 9114 ignored lines are alternative pronunciations, `word(2)` and so
on, which `mkdictdb` also skipped (only the first pronunciation is kept,
and it prints nothing for those, since they end at `(`). No other line was
ignored and every phone mapped.

The DLL is 2.7 MB, of which about 2.5 MB is the table and its index. The
packed add-on is about 1 MB.

## Lexicons

`rs_set_lexicon()` chooses between three, which the NVDA driver offers as
voices:

| Value | Dictionary | SAMPA column | Notes |
|---|---|---|---|
| `RS_LEX_CMU_AMERICAN` (default) | CMU | `ph_am` | What `choose_dialect()` picks for CMU: "wash" is W AA1 SH. |
| `RS_LEX_CMU_BRITISH` | CMU | `ph_br` | Ours. The original never pairs CMU with `ph_br`, but both columns are its own. |
| `RS_LEX_RULES` | none | — | The NRL rules alone, as `say` ran with no dictionary. |

### Observed, not changed: unstressed AH in the American column

CMU writes schwa as `AH0`. `mkdictdb` turns the `0` into a space, so
`AH0` is stored as `AH`, and `phones.def`'s American column maps `AH` to
`V` (the vowel of *strut*), not `@`. So with the default lexicon,
"hello" is `hVl'oU` where `h@l'oU` would be expected; the British column
maps `AH` to `@` and gives `h@l'@U`. This is the original's mapping and
is left as it is. Changing it is an enhancement to decide on by ear, and
would show up in the golden hashes.

## Numbers and the dictionary

CLAUDE.md asks that numbers be handled properly wherever a CMU dictionary
is used. Digits never reach the dictionary: `say.c` reads a digit run as a
number before any lookup and speaks it through `english.c`'s `cardinal()`,
whose words ("twenty", "thousand") then go through the dictionary like any
others. What was wrong with numbers was upstream of the dictionary, in how
digit runs were read; that is the front end's job and is covered in
[04-front-end.md](04-front-end.md).
