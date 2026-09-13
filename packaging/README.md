# Building the Windows ZIP

Install uv and the Visual Studio C++ build tools, then run from the repository root:

```text
uv sync --locked
uv run --locked packaging/build-portable.py
```

The build creates a fresh timestamped folder and ZIP under `dist`. Players
extract the ZIP and run `Parappa Access.exe`; they do not need Python or uv.
First Play offers to download the verified official DuckStation release and
select their own supported US game dump and PlayStation BIOS.

`release-files.txt` is the player-file allowlist. The builder adds an isolated
Python runtime, locked dependencies and their license notices, a small native
launcher, and a file-hash manifest. No emulator, game, BIOS, memory cards,
checkpoints, development tools or internal notes are bundled.

Source layout:

- `scripts`: launcher and gameplay support.
- `developer`: recording, analysis and automated investigation tools.
- `tests`: automated checks; run `uv run python -m unittest discover -s tests`.
- `packaging`: build tools, excluded from the player ZIP.

Diagnostic logging is off by default. Settings can enable bounded text support
logs; playback recordings and automated controller tests remain developer tools.
Before publishing, test first-run setup and gameplay from the extracted ZIP on
a clean Windows installation, including screen-reader navigation and audio.
The pinned DuckStation asset must still be available upstream and its hash must
match; a newer build requires compatibility validation before updating the pin.
