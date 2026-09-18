import _bootstrap
import struct
import unittest

from duckstation_subtitles import SubtitleReader, decode_subtitle

WINDOW = 0x8008ECE0
LINE_A = 0x801C3A30
LINE_B = 0x801C3A24


class FakeRAM:
    def __init__(self):
        self.memory = {}
        self.pointer = 0
        self.frames = 0

    def store(self, address, data):
        self.memory[address] = bytes(data)

    def show(self, pointer, frames):
        self.pointer, self.frames = pointer, frames

    def read(self, address, size):
        if address == WINDOW:
            window = bytearray(0x1C)
            struct.pack_into("<I", window, 4, self.pointer)
            struct.pack_into("<h", window, 0x1A, self.frames)
            return bytes(window[:size])
        data = self.memory.get(address, b"\0" * size)
        return data[:size].ljust(size, b"\0")


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
        self.ram.store(LINE_A, b"Jet Baby was really awesome!\0")
        self.ram.store(LINE_B, b"Oh yeah!\0")
        self.reader = SubtitleReader(self.ram)

    def test_speaks_each_new_line_once(self):
        self.assertIsNone(self.reader.poll())
        self.ram.show(LINE_A, 82)
        self.assertEqual(self.reader.poll(), "Jet Baby was really awesome!")
        self.ram.show(LINE_A, 60)
        self.assertIsNone(self.reader.poll())
        self.ram.show(LINE_B, 37)
        self.assertEqual(self.reader.poll(), "Oh yeah!")
        self.ram.show(0, 0)
        self.assertIsNone(self.reader.poll())

    def test_repeated_line_is_spoken_when_its_countdown_restarts(self):
        self.ram.show(LINE_B, 10)
        self.assertEqual(self.reader.poll(), "Oh yeah!")
        self.ram.show(LINE_B, 5)
        self.assertIsNone(self.reader.poll())
        self.ram.show(LINE_B, 70)
        self.assertEqual(self.reader.poll(), "Oh yeah!")

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
        self.assertEqual(self.reader.poll(), "Jet Baby was really awesome!")
        self.reader.reset()
        self.assertEqual(self.reader.poll(), "Jet Baby was really awesome!")


if __name__ == "__main__":
    unittest.main()
