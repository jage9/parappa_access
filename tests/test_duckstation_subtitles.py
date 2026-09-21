import _bootstrap
import struct
import unittest

from duckstation_subtitles import (
    ECHO,
    LYRIC,
    SCENE,
    TITLE,
    SubtitleReader,
    decode_subtitle,
    is_echo,
    suppression_reason,
    lyric_words,
)

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
CALL_LINE = 0x801C4C00
ANSWER_LINE = 0x801C4C40
ASIDE_LINE = 0x801C4C80
NEXT_CALL_LINE = 0x801C4CC0


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
        # Stage 2 chart order: two calls of the same words, each answered.
        self.store(CALL_LINE, b"Step on the brakes!\0")
        self.store(ANSWER_LINE, b"Step on the brakes!\0")
        self.store(ASIDE_LINE, b"Once more now Kick\0")
        self.store(NEXT_CALL_LINE, b"Kick\0")
        # Tables are indexed 1..count; entry 0 is unused.
        self.store(EN_TABLE, struct.pack("<3I", 0, LINE_A, LINE_B))
        self.store(DE_TABLE, struct.pack("<3I", 0, LINE_DE, LINE_B))
        record = struct.pack("<6IH", EN_TABLE, DE_TABLE, EN_TABLE, EN_TABLE, EN_TABLE, TIMING, 2)
        self.store(DESCRIPTOR, record.ljust(28, b"\0") + b"\0" * 28)
        # Like the opening movie: the first subtitle arrives well into the clip.
        self.time_first_line(minute=0, second=36)

    def time_first_line(self, minute, second, index=1):
        self.store(TIMING, struct.pack("<HBBH5h", minute, second, 15, 82, *([index] * 5)))

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

    def test_symbol_only_mumbling_is_skipped(self):
        self.assertIsNone(decode_subtitle(b"$%*?$%*&^%!*$?*\n&^&&!*&%?$%*^%!$\0"))
        self.assertIsNone(decode_subtitle(b"...!!\0"))
        self.assertEqual(decode_subtitle(b"A, aa, aaah!!\0"), "A, aa, aaah!!")

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

    def test_story_movie_title_card_line_is_a_title(self):
        # Stage movies open with the episode title at 0:00, e.g. "I need to
        # become a hero!"; the stage announcement already reads it.
        self.ram.time_first_line(minute=0, second=0)
        self.ram.show(LINE_A, 80)
        self.assertEqual(self.reader.poll(), ("Jet Baby was really awesome!", TITLE))
        self.ram.show(LINE_B, 37)
        self.assertEqual(self.reader.poll(), ("Oh yeah!", SCENE))

    def test_title_follows_the_selected_language(self):
        self.ram.time_first_line(minute=0, second=0)
        self.ram.language = 1
        self.ram.show(LINE_DE, 80)
        self.assertEqual(self.reader.poll(), ("Jet Baby war echt Wahnsinn!", TITLE))

    def test_first_line_later_in_the_movie_is_ordinary(self):
        self.ram.time_first_line(minute=0, second=36)
        self.ram.show(LINE_A, 82)
        self.assertEqual(self.reader.poll(), ("Jet Baby was really awesome!", SCENE))

    def test_second_movie_record_never_has_a_title(self):
        # Between-stage clips are later records; COMOD6's "Sunny!" opens at 0:00.
        second_timing = TIMING + 0x40
        self.ram.store(second_timing, struct.pack("<HBBH5h", 0, 0, 4, 45, 1, 1, 1, 1, 1))
        record = struct.pack("<6IH", EN_TABLE, DE_TABLE, EN_TABLE, EN_TABLE, EN_TABLE, second_timing, 2)
        self.ram.store(DESCRIPTOR + 28, record.ljust(28, b"\0"))
        self.ram.show(LINE_A, 45)
        self.assertEqual(self.reader.poll(), ("Jet Baby was really awesome!", SCENE))

    def test_reset_lets_the_same_line_speak_again(self):
        self.ram.show(LINE_A, 82)
        self.assertEqual(self.reader.poll(), ("Jet Baby was really awesome!", SCENE))
        self.reader.reset()
        self.assertEqual(self.reader.poll(), ("Jet Baby was really awesome!", SCENE))


class EchoTests(unittest.TestCase):
    def test_words_drop_case_punctuation_and_ampersands(self):
        self.assertEqual(lyric_words("Duck & Jump"), ("duck", "jump"))
        self.assertEqual(lyric_words("Ducken und Sprung"), ("ducken", "sprung"))
        self.assertEqual(lyric_words("and  Turn"), ("turn",))
        self.assertEqual(lyric_words("Here we go ! now Kick Punch Block"),
                         ("here", "we", "go", "now", "kick", "punch", "block"))
        self.assertEqual(lyric_words("...!!"), ())

    def test_plain_and_trailing_repeats_are_echoes(self):
        for call, answer in (("Punch", "Punch"),
                             ("Once more now Kick", "Kick"),
                             ("Listen carefully Jump", "Jump"),
                             ("Here we go ! now Kick Punch Block", "Kick Punch Block"),
                             ("Duck & Jump", "Duck Jump"),
                             ("Block Turn & Kick it", "Block Turn Kick"),
                             ("Ducken und Sprung", "Ducken Sprung"),
                             ("and  Turn", "Turn"),
                             ("Step on the gas!", "Step on the gas!")):
            with self.subTest(call=call, answer=answer):
                self.assertTrue(is_echo(answer, lyric_words(call)))

    def test_different_words_are_not_echoes(self):
        for call, line in (("Pose", "Listen carefully Jump"),
                           ("Do you know why we stopped the car?", "Do I know why we stopped the car?"),
                           ("Guess...", "what..."),
                           ("Kick", "Kick Punch"),
                           ("Chop Block", "Block Chop")):
            with self.subTest(call=call, line=line):
                self.assertFalse(is_echo(line, lyric_words(call)))

    def test_nothing_echoes_before_a_first_lyric(self):
        self.assertFalse(is_echo("Kick", None))
        self.assertFalse(is_echo("...", lyric_words("...")))


class LyricClassificationTests(unittest.TestCase):
    def setUp(self):
        self.ram = FakeRAM()
        self.reader = SubtitleReader(self.ram)

    def lines(self, *shown):
        result = []
        for pointer in shown:
            self.ram.show(pointer, 120)
            result.append(self.reader.poll())
        return result

    def test_answer_repeating_the_call_is_an_echo(self):
        self.assertEqual(self.lines(CALL_LINE, ANSWER_LINE),
                         [("Step on the brakes!", LYRIC), ("Step on the brakes!", ECHO)])

    def test_same_call_twice_is_spoken_both_times(self):
        kinds = [line[1] for line in self.lines(CALL_LINE, ANSWER_LINE, CALL_LINE, ANSWER_LINE)]
        self.assertEqual(kinds, [LYRIC, ECHO, LYRIC, ECHO])

    def test_trailing_repeat_after_an_aside_is_an_echo(self):
        self.assertEqual(self.lines(ASIDE_LINE, NEXT_CALL_LINE),
                         [("Once more now Kick", LYRIC), ("Kick", ECHO)])

    def test_repeat_with_restarted_countdown_and_same_pointer_is_an_echo(self):
        self.ram.show(CALL_LINE, 120)
        self.assertEqual(self.reader.poll()[1], LYRIC)
        self.ram.show(CALL_LINE, 60)
        self.assertIsNone(self.reader.poll())
        self.ram.show(CALL_LINE, 120)
        self.assertEqual(self.reader.poll()[1], ECHO)

    def test_scene_line_forgets_the_previous_lyric(self):
        kinds = [line[1] for line in self.lines(CALL_LINE, LINE_A, ANSWER_LINE)]
        self.assertEqual(kinds, [LYRIC, SCENE, LYRIC])

    def test_reset_forgets_the_previous_lyric(self):
        self.lines(CALL_LINE)
        self.reader.reset()
        self.assertEqual(self.lines(ANSWER_LINE), [("Step on the brakes!", LYRIC)])


class SuppressionTests(unittest.TestCase):
    def test_calls_speak_when_lyrics_are_on(self):
        for subtitles in (False, True):
            self.assertIsNone(suppression_reason(LYRIC, subtitles, True))

    def test_echoes_stay_silent_even_with_lyrics_on(self):
        self.assertEqual(suppression_reason(ECHO, True, True), "player_echo")

    def test_lyrics_off_silences_either_lyric_kind(self):
        for kind in (LYRIC, ECHO):
            with self.subTest(kind=kind):
                self.assertEqual(suppression_reason(kind, True, False), "lyrics_off")

    def test_title_cards_never_speak_twice(self):
        for subtitles in (False, True):
            for lyrics in (False, True):
                self.assertEqual(suppression_reason(TITLE, subtitles, lyrics), "title_card")

    def test_cut_scene_lines_follow_the_subtitle_toggle_only(self):
        for lyrics in (False, True):
            with self.subTest(lyrics=lyrics):
                self.assertIsNone(suppression_reason(SCENE, True, lyrics))
                self.assertEqual(suppression_reason(SCENE, False, lyrics), "subtitles_off")


if __name__ == "__main__":
    unittest.main()
