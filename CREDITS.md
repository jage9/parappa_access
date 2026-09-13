# Credits and third-party notices

Parappa Access is developed with JJ's accessibility design and playtesting,
with programming and investigation assisted by OpenAI Codex. Original project
code and documentation are offered under the [MIT license](LICENSE). This
does not license the game, trademarks, emulator or separately installed dependencies.

- **PaRappa the Rapper**: the original game creators, including NanaOn-Sha,
  Masaya Matsuura and Rodney Greenblat, and Sony Computer Entertainment.
  Game names and short screen labels identify the software this companion
  supports. This is an unofficial project, with no endorsement implied.
- **[DuckStation](https://www.duckstation.org/)**: Connor McLaughlin (stenzek)
  and contributors. The emulator supplies the execution, audio and debugger
  facilities used by the companion. It is downloaded separately.
  Its current [license](https://github.com/stenzek/duckstation/blob/master/LICENSE)
  is CC-BY-NC-ND-4.0; its [distribution guidance](https://github.com/stenzek/duckstation#downloading-and-running)
  allows unmodified redistribution and identifies preconfigured packages as
  modifications. This repository does not redistribute our configured copy.
- **[Prism](https://github.com/ethindp/prism)**: Ethin Probst and contributors;
  screen-reader and speech integration through the prismatoid Python package,
  under MPL-2.0. Its own NOTICE and dependency licenses accompany its releases.
- **[PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch)**, PyAudio and
  PortAudio contributors: Windows WASAPI playback and loopback capture.
  Refer to the separately installed distribution for its license notices.
- **[PCSX-Redux](https://github.com/grumpycoders/pcsx-redux)** and OpenBIOS
  contributors: the original investigation platform. Legacy probes remain
  in this repository; binaries and the local source patch are not shipped.
- **PaRappaSource researchers**, including
  [cuckydev](https://github.com/cuckydev/PaRappaSource) and
  [TheWilmster](https://github.com/TheWilmster/PaRappaSource): source-level
  research helped identify the game's runtime state.
  Decompiled game sources and extracted assets are not distributed here.
- Python, CFFI and pycparser contributors provide the runtime and speech
  binding infrastructure. Optional offline audio analysis uses NumPy and
  SciPy; they are not needed for normal launcher use.

Locally supplied cue recordings are not part of this source release. Keep
their original author and permission information before including any in a
future release. Generated cue code is part of the project source.

Before distributing a future executable, audit the actual bundled dependency
versions and include their required notices. This file is an attribution list,
not a replacement for those licenses.
