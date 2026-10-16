# 01 — Branches and where the code came from

Written 2026-10-16, when the project changed direction from a Python port
back to the original C.

## What happened

Until 2026-10-16 the `master` branch held a pure-Python port of RSynth
(`_rsynth/`), a CPython extension that sped up its Klatt filter
(`_rsynth/_klatt_c/`), an eSpeak fallback, a wxPython GUI and an NVDA
add-on that ran the Python synthesizer inside NVDA. Commit `3df8fa1`
("Strip C codebase, keep Python port for NVDA integration") had deleted
Nick Ing-Simmons' C sources to make room for it.

The direction now is the opposite: the original C engine is the
synthesizer, built as a native 64-bit library, and the add-on's only
Python is the driver NVDA requires.

## Branches

| Branch | Points at | Holds |
|---|---|---|
| `python-port` | `1bb9e46` | The Python port exactly as it was: engine, C extension, GUI, add-on 2.0.0, build scripts. Created from `master` before anything moved. Nothing on it was changed. |
| `native` | — | The work described in these documents. Merged into `master`. |
| `master` | — | The native build. |
| `main` (local) | `1122a51` | A merge of `master` with GitHub's "Initial commit" (`5652164`). Left untouched. |
| `origin/addon` | `94393cc` | An earlier add-on attempt on top of that initial commit. Left untouched. |

How it was done:

```
git branch python-port master          # park the Python work, unchanged
git switch -c native master
git rm -r _rsynth rsynth-nvda build_addon.py build_exe.py debug_synth.py \
          pyproject.toml rsynth_gui.py setup.py README.md .gitignore
git checkout 6111065 -- .              # the C tree as it was before the strip
```

`6111065` ("Remove euler.pho") is the last commit before `3df8fa1`; its tree
is the C distribution with the autotools build. That restore is commit
`20f8c28`, and it changes nothing in the C sources: `git diff 6111065
20f8c28 -- '*.c' '*.h' '*.def'` is empty. Every later change to those files
is a patch listed in [02-library-build.md](02-library-build.md).

Files the Python port left on disk (`_rsynth/` with a built `.pyd`,
`dist/`, `RSynthGUI.spec`, an old `rsynth 4.nvda-addon`) were never tracked
and were not deleted; `.gitignore` names them so they cannot be committed
by accident from this branch.

## Where the C came from

The oldest commits are Nick Ing-Simmons' own import from Perforce
(`cb950ee`, `ae0ba74`, January 2004), followed by his 2004 changes and, in
2012–2013, autotools work by Reece H. Dunn. The `README` at the top level
is Nick Ing-Simmons' and is kept as it was; this project's README is
`README.md`. Licences and credits: [../NOTICE.md](../NOTICE.md).

## Nothing was pushed

All of this is local. `rsynth-nvda` is a public repository; pushing
`master`, `native` or `python-port` is the owner's decision.
