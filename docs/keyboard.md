# DuckStation keyboard layout

In the launcher, menus show one item per line. Up/Down selects, Enter opens,
and number shortcuts still work. In Settings, Left/Right adjusts panning,
handoff sound, cue volume, spoken subtitles or spoken lyrics; Enter opens the
audio-device list. Volume changes
preview the current X sound. These launcher keys do not change game controls.

The accessible launcher now uses the stock keyboard-to-controller mapping
from the installed DuckStation build, 0.1-11893-g3b30876e9:
[GetKeyboardGenericBindingMapping](https://raw.githubusercontent.com/stenzek/duckstation/3b30876e9/src/util/input_manager.cpp).

| Key | Controller action |
| --- | --- |
| I | Triangle |
| J | Square |
| K | X / confirm |
| L | Circle / cancel where the game supports it |
| Q / E | L1 / R1 |
| 1 / 3 | L2 / R2 |
| Arrow keys | D-pad |
| Enter | Start / pause / skip scenes |
| Backspace | Select |

Accessibility helpers use Z for score, X for the current rating, U to toggle
spoken cut-scene subtitles, Y to toggle spoken rap lyrics, and ? for hints. Slash also reads hints without holding Shift. The emulator must have
focus. Helpers do not send controller buttons. The current digital-controller
setup has no analogue sticks; W/A/S/D and T/F/G/H are not reassigned as helpers.
The rating starts at Good once the gameplay HUD is active. Keyboard X can
read it then; initial Good is not automatically announced. Later rating
changes are announced automatically. Reaching Cool announces "Cool. Freestyle,
note cues off." and mutes the teacher-button cues, since Cool lets you rap
freely without following the chart. Dropping back to Good announces "Good.
Note cues on." and the cues resume.
Cut-scene subtitles are off by default; U turns them on or off and announces
Subtitles on or Subtitles off. The episode title that opens each stage's story
scene is part of the stage announcement, so it is not read again as a subtitle. The lyric lines the game shows during a rap
round use the same display and are also off by default; Y turns them on or
off and announces Lyrics on or Lyrics off. Both keys also work during the
opening scene at boot. Both choices are saved with the launcher's other
settings and hold for the next session. When
PaRappa's answer repeats the teacher's words ("Kick" after "Kick", "Kick" after
"Once more now Kick"), the repeat is skipped. An answer with different words,
like Stage 2's "Do I know why we stopped the car?", is read.

Learn sounds lists I/J/K/L/Q/E in that order, then Handoff. Arrows announce
the selected item without playing it. Enter or a letter plays the sound
without repeating its name. Handoff can be played with Enter.
With panning enabled, J/Square is 80% left and I/Triangle is 35% left,
matching their keyboard positions. Q/L1 remains 60% left; K/X, E/R1
and L/Circle remain 35%, 60% and 80% right respectively.
The handoff chirp is automatic when enabled; it has no dedicated play key.
Learn bindings and its instructions are derived from the same mapping the launcher
applies to DuckStation. Shoulder names print as "L 1" and "R 1" for pronunciation.
Native in-game hints use controller button names, such as "X Confirm" and
"Circle Cancel"; X here means the button on K, not the rating helper key.
A recognized SDL controller
continues to work alongside the keyboard.
