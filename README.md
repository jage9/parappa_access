# Parappa Access

An accessibility mod for Parappa the Rapper on PlayStation.

## About

Released in 1996, Parappa the Rapper is widely considered the first modern rhythm game, spawning an entire genre. This mod makes the original PS1 version of the game playable using modern emulation and audible cues. This mod will allow you to play all 6 stages of the game and access most game screens. If you find something that's not working or could be improved, please let me know.

## Download and start playing

[Download the latest Windows ZIP](https://github.com/jage9/parappa_access/releases/latest/download/Parappa.Access.zip)

You will need:

- A 64-bit Windows PC and an internet connection for initial setup.
- Your screen reader for spoken prompts.
- Your own US PaRappa the Rapper game dump, SCUS-94183, in a disc-image format supported by the DuckStation PlayStation emulator (listed below).
- Your own PlayStation BIOS file, such as openbios.bin.

No game or BIOS is included. The supported game version is US SCUS-94183.

Setup accepts **CCD, CUE, BIN, IMG, ISO, ECM, CHD, MDS and PBP**, plus **M3U playlists**. CCD/IMG/SUB and BIN/CUE have been tested locally. Other formats will likely work but have not been tessted. The mod will verify the version before playing.

### Getting Started

1. Make sure you have the game and bios files. The game should be unzipped. These can be placed wherever.
2. Extract the ZIP to a folder.
3. Go to this folder, and then run **Parappa Access.exe**.
4. On first launch, setup offers to download the tested official DuckStation build, then asks you to select your game rom and bios files.
5. After setup, the main menu appears. Choose **Play** to start the game.

## About the Game

The goal in Parappa the Rapper is to pass the test in each of the 6 stages. The teacher for each stage will say one or more words, and then you will match the pattern. The main accessibility feature of the mod adds sound cues to each of the words from the teacher. There are 6 sounds and buttons in the game.

If you end the round and do good enough, you can Save your progress and continue using PlayStation's memory cards. You will be asked if you want to save. Press X (k on your keyboard) to save, then use the arrow keys and X to select up to a 6 character name. You can load a saved game from the main game menu.

## What is accessible?

Parappa Access provides speech for the game's main menus, settings, stage screens, results, high scores and save/load screens. Teacher-button sounds are available across all six stages. You can also request your score, current Good/Bad/Awful/Cool rating and the current screen's controls.

The cut scenes between stages are subtitled by the game, and the mod can read each subtitle line aloud as it appears, in whatever language the game's options select. Press U while DuckStation has focus to turn spoken subtitles on or off. The lyrics shown during a rap round are a separate toggle on Y. Both are off by default, and each choice is remembered for your next session. When PaRappa answers by repeating the teacher's words, that repeat is skipped, so you hear each call once.

An optional handoff sound marks the visual transition to your response. Rating changes are announced as you play. When you reach Cool, the mod says "Cool. Freestyle, note cues off." and stops playing the teacher's note cues, because on Cool you rap freely without the note chart. If you drop back to Good, the mod says "Good. Note cues on." and the cues resume.

## Main Menu

From the main menu, you can play the game, learn game sounds, or change settings for the mod. Press 1 or Enter to play the game.

Learn sounds will let you hear the game sounds. Arrow to a sound and press Enter, or press one of the 6 buttons.

Under the settings menu, adjust the volume for the sounds, choose your audio output device, and turn sound panning on/off. You can also optionally turn the handoff sound on and off. This sound plays between the teacher and student handoff when the visual transition appears. Spoken subtitles and spoken lyrics can be switched on or off here as well; they are the same preferences that U and Y toggle in game. You can also turn on diagnostic logging if you wish to submit a bug or suggestion.

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
| 1 / 3 | L2 / R2 | (not used in Parappa)

While DuckStation has focus, these extra keys provide information:

| Key | Information |
| --- | --- |
| Z | Current score |
| X | Current rating | (works inside rounds)
| U | Toggle spoken cut-scene subtitles (off by default, remembered) |
| Y | Toggle spoken rap lyrics (off by default, remembered) |
| question mark or slash | Controls for the current screen |

Close DuckStation with Alt+F4 to return to the launcher.

A recognized game controller can theoretically also be used alongside the keyboard; connect it before choosing Play. This has not yet been tested.

See the [full keyboard guide](docs/keyboard.md) for more detail. The [sounds folder guide](sounds/README.md) explains how to replace the included WAV files.

## Todo

The cut scenes can have their subtitles spoken but are not otherwise audio-described. Some menus may include additional information not yet displayed. All main game functions should work.


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
