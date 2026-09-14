# Parappa Access

An accessibility mod for Parappa the Rapper on PlayStation.

## About

Parappa the Rapper is widely considered the first modern rhythm game, spawning an entire genre. This mod makes the original PS1 version of the game playable using modern emulation and audible cues.

## Download and start playing

[Download the latest Windows ZIP](https://github.com/jage9/parappa_access/releases/latest/download/Parappa%20Access.zip)

You will need:

- A 64-bit Windows PC and an internet connection for initial setup.
- Your screen reader for spoken prompts.
- Your own US PaRappa the Rapper game dump, SCUS-94183, in a disc-image format supported by the DuckStation PlayStation emulator (listed below).
- Your own PlayStation BIOS file, such as openbios.bin.

No game or BIOS is included. The supported game version is US SCUS-94183.

Setup accepts **CCD, CUE, BIN, IMG, ISO, ECM, CHD, MDS and PBP**, plus **M3U playlists**. CCD/IMG/SUB and BIN/CUE have been tested locally. Other formats will likely work but have not been tessted. The mod will verify the version before playing.

### Getting Started

1. Extract the ZIP to a folder.
2. Go to this folder, and then run **Parappa Access.exe**.
3. On first launch, setup offers to download the tested official DuckStation build, then asks you to select your 
4. After setup, the main menu appears. Choose **Play** to start the game.

DuckStation is downloaded into `tools/duckstation` inside your Parappa Access folder. Setup remembers your file selections. Your game and BIOS can stay in their existing folder.

## What is accessible?

Parappa Access provides speech for the game's main menus, settings, stage screens, results, high scores and save/load screens. Teacher-button sounds are available across all six stages. You can also request your score, current Good/Bad/Awful/Cool rating and the current screen's controls.

An optional handoff sound marks the visual transition to your response. Rating changes are announced as you play. 

## Main Menu

From the main menu, you can play the game, learn game sounds, or change settings for the mod. Press 1 or Enter to play the game.

Learn sounds will let you hear the game sounds. Arrow to a sound and press Enter, or press one of the 6 buttons.

Under the settings menu, adjust the volume for the sounds, choose your audio output device, and turn sound panning on/off. You can also optionally turn the handoff sound on and off. This sound plays between the teacher and student handoff when the visual transition appears. You can also turn on diagnostic logging if you wish to submit a bug or suggestion.

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
| X | Current rating | (works inside rounds)
| ? or / | Controls for the current screen |

Close DuckStation with Alt+F4 to return to the launcher.

A recognized SDL game controller can theoretically also be used alongside the keyboard; connect it before choosing Play. This has not yet been tested.

See the [full keyboard guide](docs/keyboard.md) for more detail. The [sounds folder guide](sounds/README.md) explains how to replace the included WAV files.

## Reporting a problem

If a problem can be repeated, turn on **Diagnostic logging** in Settings before playing again. Relevant files are saved under `logs/duck-sessions`, `logs/launcher-runs` and `logs/duck-prepare*`. These are text diagnostics, not microphone or playback recordings. Logs can contain local file paths; review them before sharing. You can turn logging off again afterward.

[Report an issue](https://github.com/jage9/parappa_access/issues).

## Running from source

Run from source if you want to submit changes for the mod. If you are just playing the mod, you do not need to do this.

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

## About

Parappa Access was created by Jage9 using AI-assisted coding.

## Credits and license

Parappa Access is an unofficial project. PaRappa the Rapper belongs to its original creators and rights holders. [DuckStation](https://www.duckstation.org/) provides the emulator, and Prism provides in-game screen-reader speech support.

Project code is available under the [MIT license](LICENSE). DuckStation and the other dependencies have their own licenses. See [credits and third-party notices](CREDITS.md).
