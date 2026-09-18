import _bootstrap
import struct
import unittest

from duckstation_subtitles import LYRIC, SCENE, SubtitleReader, decode_subtitle

WINDOW = 0x8008ECE0
DESCRIPTOR_SLOT = 0x800943CC
LANGUAGE_SLOT = 0x800916D8
DESCRIPTOR = 0x801C6BF8
EN_TABLE = 0x801C69C8
DE_TABLE = 0x801C6A08
TIMING = 0x801C6B08
LINE_A = 0x801C3A30
LINE_B = 0x801C3A24
LINE_DE = 0x801C3C48
LYRIC_LINE = 0x801C4B28


class FakeRAM:
    """Serve a movie table like COMOD0's, plus one lyric string outside it."""

    def __init__(self, language=0):
        self.memory = bytearray(0x40000)  # 0x801C0000..0x80200000
        self.globals = {}
        self.pointer = 0
        self.frames = 0
        self.language = language
        self.store(LINE_A, b"Jet Baby was really awesome!\0")
        self.store(LINE_B, b"Oh yeah!\0")
        self.store(LINE_DE, b"Jet Baby war echt Wahnsinn!\0")
        self.store(LYRIC_LINE, b"Yo yo yo! Check this out!\0")
        # Tables are indexed 1..count; entry 0 is unused.
        self.store(EN_TABLE, struct.pack("<3I", 0, LINE_A, LINE_B))
        self.store(DE_TABLE, struct.pack("<3I", 0, LINE_DE, LINE_B))
        record = struct.pack("<6IH", EN_TABLE, DE_TABLE, EN_TABLE, EN_TABLE, EN_TABLE, TIMING, 2)
        self.store(DESCRIPTOR, record.ljust(28, b"\0") + b"\0" * 28)

    def store(self, address, data):
        offset = address - 0x801C0000
        self.memory[offset:offset + len(data)] = data

    def show(self, pointer, frames):
        self.pointer, self.frames = pointer, frames

    def read(self, address, size):
        if address == WINDOW:
            window = bytearray(0x1C)
            struct.pack_into("<I", window, 4, self.pointer)
            struct.pack_into("<h", window, 0x1A, self.frames)
            return bytes(window[:size])
        if address == DESCRIPTOR_SLOT:
            return struct.pack("<I", self.globals.get("descriptor", DESCRIPTOR))[:size]
        if address == LANGUAGE_SLOT:
            return struct.pack("<h", self.language)[:size]
        offset = address - 0x801C0000
        if not 0 <= offset < len(self.memory):
            return b"\0" * size
        return bytes(self.memory[offset:offset + size]).ljust(size, b"\0")


class DecodeSubtitleTests(unittest.TestCase):
    def test_newlines_become_spaces(self):
        self.assertEqual(decode_subtitle(b"(Boy, she sure is beautiful\ntoday...)\0junk"),
                         "(Boy, she sure is beautiful today...)")

    def test_latin1_accents_survive(self):
        self.assertEqual(decode_subtitle(b"Voil\xe0.\0"), "Voilà.")

    def test_empty_or_binary_buffers_are_rejected(self):
        self.assertIsNone(decode_subtitle(b"\0"))
        self.assertIsNone(decode_subtitle(b"\x01\x02abc\0"))
        self.assertIsNone(decode_subtitle(b"   \n \0"))
        self.assertIsNone(decode_subtitle(None))


class SubtitleReaderTests(unittest.TestCase):
    def setUp(self):
        self.ram = FakeRAM()
        self.reader = SubtitleReader(self.ram)

    def test_speaks_each_new_line_once(self):
        self.assertIsNone(self.reader.poll())
        self.ram.show(LINE_A, 82)
        self.assertEqual(self.reader.poll(), ("Jet Baby was really awesome!", SCENE))
        self.ram.show(LINE_A, 60)
        self.assertIsNone(self.reader.poll())
        self.ram.show(LINE_B, 37)
        self.assertEqual(self.reader.poll(), ("Oh yeah!", SCENE))
        self.ram.show(0, 0)
        self.assertIsNone(self.reader.poll())

    def test_repeated_line_is_spoken_when_its_countdown_restarts(self):
        self.ram.show(LINE_B, 10)
        self.assertEqual(self.reader.poll(), ("Oh yeah!", SCENE))
        self.ram.show(LINE_B, 5)
        self.assertIsNone(self.reader.poll())
        self.ram.show(LINE_B, 70)
        self.assertEqual(self.reader.poll(), ("Oh yeah!", SCENE))

    def test_line_outside_the_movie_table_is_a_lyric(self):
        self.ram.show(LYRIC_LINE, 120)
        self.assertEqual(self.reader.poll(), ("Yo yo yo! Check this out!", LYRIC))
        self.ram.show(LINE_A, 82)
        self.assertEqual(self.reader.poll(), ("Jet Baby was really awesome!", SCENE))

    def test_classification_follows_the_selected_language(self):
        self.ram.language = 1
        self.ram.show(LINE_DE, 82)
        self.assertEqual(self.reader.poll(), ("Jet Baby war echt Wahnsinn!", SCENE))
        self.ram.show(LINE_A, 82)
        self.assertEqual(self.reader.poll(), ("Jet Baby was really awesome!", LYRIC))

    def test_missing_or_garbage_descriptor_makes_everything_a_lyric(self):
        for descriptor in (0, 0x80010000, 0x801C3A30):
            with self.subTest(descriptor=hex(descriptor)):
                self.ram.globals["descriptor"] = descriptor
                reader = SubtitleReader(self.ram)
                self.ram.show(LINE_A, 82)
                self.assertEqual(reader.poll(), ("Jet Baby was really awesome!", LYRIC))

    def test_pointer_outside_overlay_ram_is_ignored(self):
        self.ram.show(0x80010000, 50)
        self.assertIsNone(self.reader.poll())
        self.ram.show(0x801FFFF0, 50)
        self.assertIsNone(self.reader.poll())

    def test_short_window_read_is_ignored(self):
        class Short(FakeRAM):
            def read(self, address, size):
                return b"\0" * 4
        self.assertIsNone(SubtitleReader(Short()).poll())

    def test_reset_lets_the_same_line_speak_again(self):
        self.ram.show(LINE_A, 82)
        self.assertEqual(self.reader.poll(), ("Jet Baby was really awesome!", SCENE))
        self.reader.reset()
        self.assertEqual(self.reader.poll(), ("Jet Baby was really awesome!", SCENE))


if __name__ == "__main__":
    unittest.main()
