"""Read the subtitle line the game is currently drawing.

Each stage overlay (COMODn.BIN, loaded at 0x801C3870) carries its movie
subtitles as NUL-terminated Latin-1 strings in five languages plus a timing
table. The movie player registers that table at 0x800943CC and the EXE's
subtitle engine (0x80024C84 setup, 0x80024CF8 per-frame update) compares the
STR clock against it. The engine keeps the line it is showing in two globals:

- 0x8008ECE4: pointer to the current line's string, 0 when nothing is shown.
- 0x8008ECFA: signed frames left before the line is cleared.

The overlays' own lyric display during a rap round writes the same pointer
(a 120-frame countdown from the chart's lyric byte), so a line is classed as
a cut-scene subtitle only when its string belongs to the registered movie
table for the language chosen in the game's options.

Rap lyrics come in call-and-response pairs. The chart gives the teacher's
call and PaRappa's answer separate strings, but the answer repeats the
teacher's words (Stage 1: "Kick" / "Kick"; "Once more now Kick" / "Kick";
Stage 2: "Step on the gas!" twice). Nothing in the game state marks whose
line is on screen: the flags word at 0x801C3640 is zeroed every frame by the
overlay's input loop and bit 0 only records a button press, and the cursor
fields stay on PaRappa's response while the teacher's overlapping asides
("Once more now", "Listen carefully") are shown. So an answer is recognised
by its text: a lyric whose words repeat, or trail, the previous lyric.
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
TITLE = "title"
LYRIC = "lyric"
ECHO = "echo"
_TIMING_ENTRY = 16


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
    # Stage 1 shows lines of pure symbols for Chop Chop Master Onion's
    # mumbling; there is nothing to say for those.
    if not any(c.isalpha() for c in text):
        return None
    return text


_CONNECTORS = frozenset(("and", "und", "et", "e", "y"))  # EN DE FR IT ES


def lyric_words(text):
    """The words of a lyric, lower-cased, without punctuation or connectors.

    "Duck & Jump", "Duck and Jump" and "Duck Jump" are the same answer, as
    are "Ducken und Sprung" and "Ducken Sprung" in the German text.
    """
    cleaned = "".join(c if c.isalnum() else " " for c in text.lower())
    return tuple(word for word in cleaned.split() if word not in _CONNECTORS)


def is_echo(text, previous):
    """True when text's words appear, in order and unbroken, in previous.

    Covers the plain repeat ("Punch" after "Punch"), the trailing repeat
    ("Kick" after "Once more now Kick", "Jump" after "Listen carefully
    Jump") and the shortened repeat ("Block Turn Kick" after "Block Turn &
    Kick it"). A line with different words, such as PaRappa's "Do I know
    why we stopped the car?" answering "Do you know...", is not an echo.
    """
    if previous is None:
        return False
    words = lyric_words(text)
    if not words:
        return False
    span = len(words)
    return any(previous[i:i + span] == words for i in range(len(previous) - span + 1))


def suppression_reason(kind, subtitles_enabled, lyrics_enabled):
    """Why a subtitle line must stay silent, or None to speak it.

    Cut-scene subtitles follow the U toggle, rap lyrics the Y toggle, and
    PaRappa's echoes never speak. The episode title that opens each stage's
    story movie is already part of the stage announcement, so its subtitle
    is never read a second time.
    """
    if kind == TITLE:
        return "title_card"
    if kind == SCENE:
        return None if subtitles_enabled else "subtitles_off"
    if not lyrics_enabled:
        return "lyrics_off"
    if kind == ECHO:
        return "player_echo"
    return None


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
        self._title_lines = frozenset()
        self._previous_lyric = None

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
        if self._is_scene_line(pointer):
            self._previous_lyric = None
            return text, (TITLE if pointer in self._title_lines else SCENE)
        return text, self._classify_lyric(text)

    def _classify_lyric(self, text):
        """LYRIC for a call, ECHO for the answer that repeats it.

        Calls and answers alternate, so an answer never has an echo of its
        own: the next identical line is the teacher calling again (Stage 2
        repeats "Step on the brakes!" as two consecutive calls).
        """
        if is_echo(text, self._previous_lyric):
            self._previous_lyric = None
            return ECHO
        self._previous_lyric = lyric_words(text)
        return LYRIC

    def _is_scene_line(self, pointer):
        descriptor = struct.unpack("<I", self.ram.read(_DESCRIPTOR, 4))[0]
        language = struct.unpack("<h", self.ram.read(_LANGUAGE, 2))[0]
        key = (descriptor, language)
        if key != self._scene_key or pointer not in self._scene_lines:
            self._scene_key = key
            self._scene_lines, self._title_lines = self._movie_lines(descriptor, language)
        return pointer in self._scene_lines

    def _movie_lines(self, descriptor, language):
        """(every string pointer the movie table can show, the title-card lines).

        Each stage's story movie (record 0) opens with its episode title as
        a subtitle at movie time 0:00 ("I need to become a hero!"), which the
        stage announcement already reads. The opening movie's first line
        comes at 0:36 and the short between-stage clips are later records,
        so neither is treated as a title.
        """
        if not _in_ram(descriptor, _RECORD_SIZE) or not 0 <= language < _LANGUAGES:
            return frozenset(), frozenset()
        lines = set()
        titles = set()
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
            pointers = struct.unpack(f"<{count}I", entries)
            lines.update(pointers)
            if movie == 0:
                titles.update(self._title_line(tables[5], pointers, language))
        return frozenset(lines), frozenset(titles)

    def _title_line(self, timing, pointers, language):
        if not _in_ram(timing, _TIMING_ENTRY):
            return ()
        entry = self.ram.read(timing, _TIMING_ENTRY)
        minute, second = struct.unpack_from("<HB", entry, 0)
        index = struct.unpack_from("<5h", entry, 6)[language]
        if minute or second or not 0 < index <= len(pointers):
            return ()
        return (pointers[index - 1],)
