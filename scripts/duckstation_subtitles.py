"""Read the subtitle line the game is currently drawing.

Each stage overlay (COMODn.BIN, loaded at 0x801C3870) carries its movie
subtitles as NUL-terminated Latin-1 strings in five languages plus a timing
table. The movie player registers that table at 0x800943CC and the EXE's
subtitle engine (0x80024C84 setup, 0x80024CF8 per-frame update) compares the
STR clock against it. The engine keeps the line it is showing in two globals:

- 0x8008ECE4: pointer to the current line's string, 0 when nothing is shown.
- 0x8008ECFA: signed frames left before the line is cleared.

The overlays' own lyric display during a rap round writes the same pointer,
so a line is classed as a cut-scene subtitle only when its string belongs to
the registered movie table for the language chosen in the game's options.
"""
import struct

_WINDOW_START = 0x8008ECE0
_WINDOW_SIZE = 0x1C
_POINTER_OFFSET = 0x8008ECE4 - _WINDOW_START
_FRAMES_OFFSET = 0x8008ECFA - _WINDOW_START
_DESCRIPTOR = 0x800943CC
_LANGUAGE = 0x800916D8
_OVERLAY_START = 0x801C3870
_RAM_END = 0x80200000
_MAX_LINE = 192
_RECORD_SIZE = 28
_MAX_MOVIES = 4
_MAX_LINES = 200
_LANGUAGES = 5

SCENE = "scene"
LYRIC = "lyric"


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


def _in_ram(pointer, size=4):
    return _OVERLAY_START <= pointer <= _RAM_END - size


class SubtitleReader:
    """Report each subtitle line once, as the game's engines show it."""

    def __init__(self, ram):
        self.ram = ram
        self.reset()

    def reset(self):
        self.pointer = 0
        self.frames = 0
        self._scene_key = None
        self._scene_lines = frozenset()

    def poll(self):
        """Return (text, kind) for a newly shown line, else None."""
        window = self.ram.read(_WINDOW_START, _WINDOW_SIZE)
        if len(window) < _WINDOW_SIZE:
            return None
        pointer = struct.unpack_from("<I", window, _POINTER_OFFSET)[0]
        frames = struct.unpack_from("<h", window, _FRAMES_OFFSET)[0]
        # A repeated line keeps its pointer but restarts its countdown.
        fresh = pointer != self.pointer or frames > self.frames
        self.pointer, self.frames = pointer, frames
        if not fresh or pointer == 0 or not _in_ram(pointer, _MAX_LINE):
            return None
        text = decode_subtitle(self.ram.read(pointer, _MAX_LINE))
        if text is None:
            return None
        return text, (SCENE if self._is_scene_line(pointer) else LYRIC)

    def _is_scene_line(self, pointer):
        descriptor = struct.unpack("<I", self.ram.read(_DESCRIPTOR, 4))[0]
        language = struct.unpack("<h", self.ram.read(_LANGUAGE, 2))[0]
        key = (descriptor, language)
        if key != self._scene_key or pointer not in self._scene_lines:
            self._scene_key = key
            self._scene_lines = self._movie_lines(descriptor, language)
        return pointer in self._scene_lines

    def _movie_lines(self, descriptor, language):
        """Every string pointer the registered movie table can show."""
        if not _in_ram(descriptor, _RECORD_SIZE) or not 0 <= language < _LANGUAGES:
            return frozenset()
        lines = set()
        for movie in range(_MAX_MOVIES):
            address = descriptor + movie * _RECORD_SIZE
            if not _in_ram(address, _RECORD_SIZE):
                break
            record = self.ram.read(address, _RECORD_SIZE)
            tables = struct.unpack_from("<6I", record, 0)
            count = struct.unpack_from("<H", record, 24)[0]
            if not all(_in_ram(t) for t in tables) or not 0 < count <= _MAX_LINES:
                continue
            table = tables[language]
            if not _in_ram(table + 4, 4 * count):
                continue
            entries = self.ram.read(table + 4, 4 * count)
            lines.update(struct.unpack(f"<{count}I", entries))
        return frozenset(lines)
