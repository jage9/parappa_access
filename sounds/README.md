# Replaceable button sounds

Put your own short recordings here as `circle.wav`, `x.wav`, `square.wav`,
`triangle.wav`, `l1.wav`, and `r1.wav`. The demo loads them once before play.
Local files may include user-supplied replacements; they are not included in
the source release. WAV files here are ignored by Git so recordings are not
accidentally committed. The DuckStation launcher currently requires all six
files; the generated fallback described below belongs to the legacy Lua demo.

During early testing, the six WAVs and generated fallback tones were amplified by
40% for testing (1.4 times the previous sample amplitude, about +2.92 dB).
Their duration remains about 112 ms. All six were checked for clipping.
X and Circle use an additional 40% amplitude increase. X uses a high square
wave; Circle uses a sawtooth with its existing up/down pitch motion.
Replacement recordings play at their own file level; no extra gain is
automatically applied to imported files.

Use uncompressed 16-bit or 24-bit PCM, mono or stereo, 8-192 kHz, at most 250 ms.
24-bit sources convert to 16-bit playback in memory at startup. Source files
are not rewritten. DuckStation applies the selected cue volume and resamples
in memory when required by the selected output device.
The short duration limit is for this early rhythm demo. Missing files use the
built-in defaults; malformed existing files stop audio initialization.

The accessibility menu can optionally pan the six cues. When panning is on,
it reads the WAVs into memory, converts each cue to stereo 16-bit PCM, and
uses equal-power positions: Triangle -35%, L1 -60%, Square -80%, X +35%,
R1 +60%, and Circle +80%. A stereo replacement is first mixed to mono so its
position is predictable. The files in this directory are never rewritten.

For a standalone audition or export, write `on` to `logs/demo-panning.txt`
before launching; any other value or a missing file leaves the original bytes
and channel layout unchanged. The menu writes this option automatically and
keeps panning enabled by default. The selected position is available through
`sounds.source(name)` as `info.pan`, with `sounds.panEnabled` reporting the
current mode.

Convert an OGG, MP3, FLAC, or other FFmpeg-supported source with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/import-earcon.ps1 -InputPath "C:\path\circle.ogg" -Button CIRCLE -Force
```

`-Force` explicitly replaces an existing button file. Without it, existing
files are preserved. Conversion does not trim long recordings or insert
silence. Audition the result before playing. OGG is converted to PCM once;
there is no decoding or file access at individual note events.
