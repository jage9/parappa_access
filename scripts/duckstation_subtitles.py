"""Read the cut-scene subtitle the game is currently drawing.

Each stage overlay (COMODn.BIN, loaded at 0x801C3870) carries its movie
subtitles as NUL-terminated Latin-1 strings in five languages plus a timing
table. The movie player registers that table at 0x800943CC and the EXE's
subtitle engine (0x80024C84 setup, 0x80024CF8 per-frame update) compares the
STR clock against it. The engine keeps the line it is showing in two globals:

- 0x8008ECE4: pointer to the current line's string, 0 when nothing is shown.
- 0x8008ECFA: signed frames left before the line is cleared.

The pointer already reflects the language chosen in the game's options, so the
launcher speaks whatever text is on screen.
"""
import struct

_WINDOW_START = 0x8008ECE0
_WINDOW_SIZE = 0x1C
_POINTER_OFFSET = 0x8008ECE4 - _WINDOW_START
_FRAMES_OFFSET = 0x8008ECFA - _WINDOW_START
_OVERLAY_START = 0x801C3870
_RAM_END = 0x80200000
_MAX_LINE = 192


def decode_subtitle(data):
    """Return the spoken form of a raw subtitle buffer, or None if unusable."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        return None
    raw = bytes(data)
    end = raw.find(b"\0")
    if end <= 0:
        return None
    raw = raw[:end]
    if any(b < 0x20 and b not in (0x0A, 0x0D) for b in raw):
        return None
    text = " ".join(raw.decode("latin-1").split())
    return text or None


class SubtitleReader:
    """Speak each subtitle line once, as the game's movie player shows it."""

    def __init__(self, ram):
        self.ram = ram
        self.reset()

    def reset(self):
        self.pointer = 0
        self.frames = 0

    def poll(self):
        window = self.ram.read(_WINDOW_START, _WINDOW_SIZE)
        if len(window) < _WINDOW_SIZE:
            return None
        pointer = struct.unpack_from("<I", window, _POINTER_OFFSET)[0]
        frames = struct.unpack_from("<h", window, _FRAMES_OFFSET)[0]
        # A repeated line keeps its pointer but restarts its countdown.
        fresh = pointer != self.pointer or frames > self.frames
        self.pointer, self.frames = pointer, frames
        if not fresh or pointer == 0:
            return None
        if not _OVERLAY_START <= pointer <= _RAM_END - _MAX_LINE:
            return None
        return decode_subtitle(self.ram.read(pointer, _MAX_LINE))
