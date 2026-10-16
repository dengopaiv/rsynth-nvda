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
| `python-port` | `1bb9e46` | The Python port exactly as it was: engine, C extension, the wxPython GUI (`rsynth_gui.py`, packaged by `build_exe.py`), add-on 2.0.0, build scripts. Created from `master` before anything moved. Nothing on it was changed. The GUI's native replacement on `master` is [07](07-gui.md). |
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

The Python port also left untracked build output on disk: `_rsynth/` with
a built `.pyd`, `build/` and `dist/` (a PyInstaller GUI build and add-on
1.0.1), `RSynthGUI.spec` and an old `rsynth 4.nvda-addon`. All of it was
generated, and can be generated again from the `python-port` branch. It
was deleted on 2026-10-16 at the user's request, so the only add-on left
in the folder is the current `nvda-addon/rsynth-<version>.nvda-addon`.
`.gitignore` still names those paths, in case checking out `python-port`
and building there brings them back. Since the native GUI ([07](07-gui.md)),
`dist/` is used again, for its latest build, `dist/rsynth_gui.exe`.

## Where the C came from

The oldest commits are Nick Ing-Simmons' own import from Perforce
(`cb950ee`, `ae0ba74`, January 2004), followed by his 2004 changes and, in
2012–2013, autotools work by Reece H. Dunn. The `README` at the top level
is Nick Ing-Simmons' and is kept as it was; this project's README is
`README.md`. Licences and credits: [../NOTICE.md](../NOTICE.md).

## Nothing was pushed

All of this is local. `rsynth-nvda` is a public repository; pushing
`master`, `native` or `python-port` is the owner's decision.
