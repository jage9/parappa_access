# Parappa Access

Play PaRappa the Rapper with spoken menus and sounds for the teacher's button cues. Parappa Access brings screen-reader support to the original US PlayStation game, running in DuckStation on Windows.

Follow Chop Chop Master Onion, learn the rhythms, and work your way through all six stages. The game keeps its original music, dialogue and controls. Each button has its own sound so you can hear the teacher's demonstration, then play your response.

## Download and start playing

[Download the latest Windows ZIP](https://github.com/jage9/parappa_access/releases/latest/download/Parappa%20Access.zip)

The download link will become available when the first release is published. You can also find release notes on the [releases page](https://github.com/jage9/parappa_access/releases).

You will need:

- A 64-bit Windows PC and an internet connection for initial setup.
- Your screen reader. NVDA has been used throughout development and testing.
- Your own US PaRappa the Rapper game dump, SCUS-94183, in a disc-image format supported by DuckStation (listed below).
- Your own PlayStation BIOS file.

No game or BIOS is included. The supported game version is US SCUS-94183.

Setup accepts **CCD, CUE, BIN, IMG, ISO, ECM, CHD, MDS and PBP**, plus **M3U playlists**. CCD/IMG/SUB and BIN/CUE have been tested locally. Other formats are experimental: DuckStation must be able to read them, and the loaded game executable must match our supported version before accessibility playback starts. This check identifies the game version; it does not verify every music or video asset.

Extract RAR, ZIP and 7z archives first. For multi-file images, select the descriptor (`.ccd`, `.cue` or `.mds`) and keep its data files together. A file extension alone does not make an image compatible.

1. Extract the whole ZIP to a folder where you can save files. Keep its folders together.
2. Open **Parappa Access.exe**. You do not need to install Python or any development tools.
3. On first launch, setup offers to download the tested official DuckStation build, then asks you to select your game image or descriptor and your BIOS. Keep any companion disc files beside it. Canceling setup closes the launcher; run it again when you are ready.
4. After setup, the main menu appears. Choose **Play** to start the game, including its opening screens.

DuckStation is downloaded into `tools/duckstation` inside your Parappa Access folder. Setup remembers your file selections. Your game and BIOS can stay in their existing folder.

## What is accessible?

Parappa Access provides speech for the game's main menus, settings, stage screens, results, high scores and save/load screens. Teacher-button sounds are available across all six stages. You can also request your score, current Good/Bad/Awful/Cool rating and the current screen's controls.

An optional handoff sound marks the visual transition to your response. Rating changes are announced as you play. The button cues follow the teacher's demonstration; there are no note prompts during your response, and the game's scoring is unchanged.

This is an early release for testing. Detailed descriptions of the animated cutscenes are not included; the game's existing voices and music still play. Please report missing speech, incorrect cues or timing problems.

## Launcher menus

The main menu has **1 Play, 2 Learn sounds, 3 Settings, 0 Exit**. Use Up/Down and Enter, or press a number without Enter. The Windows controls support screen-reader navigation and review.

Start with **Learn sounds** to get familiar with the six buttons. Arrow to a sound and press Enter to hear it, or press its letter key directly. Moving through the list does not play the sounds. The handoff sound is also in the list.

In **Settings**, you can change:

- **Cue panning:** spread the button sounds from left to right, or keep them centered.
- **Audio device:** choose where game audio and cues play. System default follows your Windows output device. Screen-reader output is controlled separately by your screen reader.
- **Handoff sound:** turn the teacher-to-player marker on or off.
- **Cue volume:** adjust from 0 to 200 percent. A centered X sound previews changes.
- **Diagnostic logging:** record text information for troubleshooting. This is off by default.

Use Left/Right to adjust a setting. For audio devices, you can also press Enter to open the full list.

## Playing with the keyboard

These are the controller buttons used by the launcher:

| Key | Button or action |
| --- | --- |
| I | Triangle |
| J | Square |
| K | X; confirm in menus |
| L | Circle; cancel where supported |
| Q | L1 |
| E | R1 |
| Arrow keys | Directional pad |
| Enter | Start; pause or skip scenes |
| Backspace | Select |
| 1 / 3 | L2 / R2 |

While DuckStation has focus, these extra keys provide information:

| Key | Information |
| --- | --- |
| Z | Current score |
| X | Current rating |
| ? or / | Controls for the current screen |

The keyboard's **K** key presses the controller's **X** button. The keyboard's **X** key reads the rating. Spoken game hints use controller button names.

Close DuckStation with Alt+F4 to return to the launcher. A recognized SDL game controller can also be used alongside the keyboard; connect it before choosing Play. Controller support still needs broader hardware testing.

See the [full keyboard guide](docs/keyboard.md) for more detail. The [sounds folder guide](sounds/README.md) explains how to replace the included WAV files.

## Reporting a problem

Please include the stage or screen, what you did, and what you heard or expected to hear. For timing problems, mention whether the game's music also stuttered or only the added cues sounded wrong.

If a problem can be repeated, turn on **Diagnostic logging** in Settings before playing again. Relevant files are saved under `logs/duck-sessions`, `logs/launcher-runs` and `logs/duck-prepare*`. These are text diagnostics, not microphone or playback recordings. Logs can contain local file paths; review them before sharing. You can turn logging off again afterward.

[Report an issue](https://github.com/jage9/parappa_access/issues).

## Running from source

Developers need [uv](https://docs.astral.sh/uv/getting-started/installation/) and a Windows checkout of this repository. From the repository folder:

```bat
uv sync --locked
```

Start the launcher directly. Its first-launch setup is the same as in the release ZIP:

```bat
uv run --locked scripts/accessible-menu.py
```

After setup, you can also double-click `Parappa Access.bat`.

Run the tests with:

```bat
uv run --locked python -m unittest discover -s tests
```

The source is organized into `scripts` for the launcher and gameplay support, `developer` for investigation tools, `tests` for automated checks, and `packaging` for the release builder. Developer tools are excluded from the player ZIP. Some investigation tools require local checkpoints or recordings that are not distributed.

## Building a release ZIP

Install the Visual Studio C++ build tools with the Windows SDK, then run:

```bat
uv sync --locked
uv run --locked packaging/build-portable.py
```

The builder creates a fresh timestamped folder and **Parappa Access.zip** under `dist`. It includes the launcher EXE, an isolated Python runtime, locked dependencies, seven sounds and license notices. DuckStation is downloaded during first-run setup; game files, BIOS files and saved games are never bundled.

See [packaging instructions](https://github.com/jage9/parappa_access/blob/main/packaging/README.md) for build checks. Upload the resulting file as **Parappa Access.zip** when publishing a GitHub release so the download link above works.

## Credits and license

Parappa Access is an unofficial project. PaRappa the Rapper belongs to its original creators and rights holders. [DuckStation](https://www.duckstation.org/) provides the emulator, and Prism provides in-game screen-reader speech support.

Project code is available under the [MIT license](LICENSE). DuckStation and the other dependencies have their own licenses. See [credits and third-party notices](CREDITS.md) for acknowledgments and sound credits.
