# Parappa Access

An experimental Windows accessibility companion for the US PlayStation game
PaRappa the Rapper (SCUS-94183), using DuckStation. It provides spoken menus,
teacher-button sounds, optional teacher/student handoff audio, and on-demand
score and rating announcements. It does not provide response-note prompts or
change the game's scoring windows.

This is an initial **source release**, not a self-contained installer. The
existing local testing setup works; a fresh checkout still requires manual
preparation. No game, BIOS, emulator, saved games or third-party sound recordings
are included. See [credits and third-party notices](CREDITS.md) and [license](LICENSE).

## Running the existing setup

From the repository directory in Command Prompt:

```bat
python scripts/accessible-menu.py
```

The native Windows menu offers Play, Learn sounds, Settings and Exit.
Use arrows and Enter or number keys. Learn sounds lists I, J, K, L, Q, E,
then Handoff. Enter plays the selected sound; letter keys play directly.
See [keyboard controls](docs/keyboard.md).

## Preparing another computer

The current adapter is Windows-specific and uses 64-bit Python (3.10 or newer),
Windows PowerShell, Prism and PyAudioWPatch. Install the Python runtime dependencies:

```bat
python -m pip install -r requirements.txt
```

Download DuckStation separately from its [official website](https://www.duckstation.org/).
Our tested Windows build is 0.1.11893, revision
`3b30876e92f28faeaba06bcfa562939c7107961e`. A newer build is not automatically
validated.
The current scripts expect its portable files in
`tools/research/duckstation-stock/portable/`, including
`duckstation-qt-x64-ReleaseLTCG.exe`, `portable.txt` and a locally created
`settings.ini`. Configure a BIOS you are entitled to use; none is supplied.

Place your own matching US disc dump in [game/](game/README.md), and supply the
six short WAVs described in [sounds/](sounds/README.md). The existing local
replacement sounds are intentionally excluded until their redistribution
permissions are established.

There are still setup dependencies to remove before general testing: the disc
filename and emulator path are fixed, the normal Play path imports an existing
Redux memory-card configuration, and the verified BIOS/audio settings need a
first-run setup flow. A fresh checkout will not automatically create these.
Do not copy someone else's cards, BIOS or game to satisfy these requirements.

## Development and internal testing

```bat
python -m unittest discover -s scripts -p "test_*.py"
```

Source probes and tests are included so investigation remains reproducible.
Internal research notes, logs, emulator installations, extracted assets, memory cards,
checkpoints and captures stay local and ignored. No internal testing files
need to be deleted to make a clean commit. Developer playback tools are for
investigation, not enabled by normal Play.

Internal project notes remain available locally and are not published in Git.
