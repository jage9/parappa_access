"""Hardware-free tests for verified DuckStation card-screen speech."""

import struct
import unittest

from duckstation_card_speech import (
    DuckStationCardSpeechReader,
    HIGHSCORE_WAIT_STATE,
    SLOT_NAME_OFFSET,
    SLOT_NAME_TABLE,
    SLOT_RECORD_STRIDE,
    SLOT_STATE,
)
from duckstation_menu import (
    CARD_MODE_DISPATCH,
    CARD_MODE_DISPATCH_WORD,
    NAME_KEYBOARD,
    NAME_STATE,
)


RAM_BASE = 0x80000000
RAM_SIZE = 0x200000


class FakeRAM:
    def __init__(self):
        self.data = bytearray(RAM_SIZE)

    def read(self, address, size):
        offset = address - RAM_BASE
        if not 0 <= offset <= RAM_SIZE - size:
            raise ValueError("read outside fake PS1 RAM")
        return bytes(self.data[offset : offset + size])

    def write(self, address, data):
        offset = address - RAM_BASE
        if not 0 <= offset <= RAM_SIZE - len(data):
            raise ValueError("write outside fake PS1 RAM")
        self.data[offset : offset + len(data)] = data

    def word(self, address, value):
        self.write(address, struct.pack("<I", value))

    def short(self, address, value):
        self.write(address, struct.pack("<h", value))


def dispatcher(ram, *, valid=True):
    ram.word(
        CARD_MODE_DISPATCH,
        CARD_MODE_DISPATCH_WORD if valid else 0,
    )


def name_state(ram, *, cursor=0, name=b"", keyboard_pointer=NAME_KEYBOARD, count=57):
    state = bytearray(0x22)
    struct.pack_into("<I", state, 0x0C, keyboard_pointer)
    struct.pack_into("<hhh", state, 0x14, count, cursor, len(name))
    state[0x1C : 0x1C + len(name)] = name
    ram.write(NAME_STATE, state)

    keyboard = bytearray(57)
    keyboard[:4] = bytes((45, 10, 33, ord("A")))
    ram.write(NAME_KEYBOARD, keyboard)


def slot_state(ram, *, cursor=0, count=16):
    state = bytearray(0x16)
    struct.pack_into("<h", state, 0x10, count)
    struct.pack_into("<h", state, 0x14, cursor)
    ram.write(SLOT_STATE, state)


def slot_name(ram, index, value):
    address = SLOT_NAME_TABLE + index * SLOT_RECORD_STRIDE + SLOT_NAME_OFFSET
    encoded = value.encode("ascii")[:6]
    ram.write(address, encoded.ljust(6, b"\0"))


class DuckStationCardSpeechTests(unittest.TestCase):
    def test_loading_message_requires_slot_state_and_has_no_controls(self):
        ram = FakeRAM()
        dispatcher(ram)
        reader = DuckStationCardSpeechReader(ram)
        self.assertEqual(reader.poll((16, NAME_STATE)), [])
        self.assertEqual(reader.poll((16, SLOT_STATE)), ["Don't remove memory card."])
        self.assertEqual(reader.hint(), "")
        self.assertEqual(reader.poll((16, SLOT_STATE)), [])

    def test_overwrite_question_requires_slot_context_and_reads_once(self):
        ram = FakeRAM()
        dispatcher(ram)
        reader = DuckStationCardSpeechReader(ram)
        self.assertEqual(reader.poll((22, NAME_STATE)), [])
        self.assertEqual(reader.poll((22, SLOT_STATE)), ["OK to overwrite? Yes. No."])
        self.assertEqual(reader.hint(), "X Yes. Circle No.")
        self.assertEqual(reader.poll((22, SLOT_STATE)), [])
        self.assertEqual(reader.poll(None), [])
        self.assertEqual(reader.hint(), "")

    def test_saving_message_announces_once_without_name_editing_hint(self):
        ram = FakeRAM()
        dispatcher(ram)
        name_state(ram)
        reader = DuckStationCardSpeechReader(ram)
        reader.poll((10, NAME_STATE))
        self.assertTrue(reader.hint())
        self.assertEqual(reader.poll((15, NAME_STATE)), ["Now saving."])
        self.assertEqual(reader.hint(), "")
        self.assertEqual(reader.poll((15, NAME_STATE)), [])
        self.assertEqual(reader.poll((15, SLOT_STATE)), [])

    def test_missing_card_text_and_exit_hint_require_active_state(self):
        ram = FakeRAM()
        dispatcher(ram)
        reader = DuckStationCardSpeechReader(ram)
        context = (5, HIGHSCORE_WAIT_STATE)
        self.assertEqual(reader.poll((5, SLOT_STATE)), [])
        self.assertEqual(reader.poll(context), ["Insert Memory card! Exit."])
        self.assertEqual(reader.hint(), "X Exit.")
        self.assertEqual(reader.poll(context), [])
        self.assertEqual(reader.poll(None), [])
        self.assertEqual(reader.hint(), "")
        dispatcher(ram, valid=False)
        self.assertEqual(reader.poll(context), [])

    def test_save_question_announces_once_and_none_resets_hint(self):
        ram = FakeRAM()
        dispatcher(ram)
        reader = DuckStationCardSpeechReader(ram)

        self.assertEqual(reader.poll((2, None)), ["Save? Yes. No."])
        self.assertEqual(reader.hint(), "X Yes. Circle No.")
        self.assertEqual(reader.poll((2, None)), [])

        self.assertEqual(reader.poll(None), [])
        self.assertEqual(reader.hint(), "")
        self.assertEqual(reader.poll((2, None)), ["Save? Yes. No."])

    def test_highscore_loading_wait_requires_the_verified_state_and_announces_once(self):
        ram = FakeRAM()
        dispatcher(ram)
        reader = DuckStationCardSpeechReader(ram)

        self.assertEqual(reader.poll((17, SLOT_STATE)), [])
        self.assertEqual(reader.hint(), "")

        context = (17, HIGHSCORE_WAIT_STATE)
        self.assertEqual(reader.poll(context), ["Please wait a minute."])
        self.assertEqual(reader.hint(), "")
        self.assertEqual(reader.poll(context), [])

        self.assertEqual(reader.poll(None), [])
        self.assertEqual(reader.poll(context), ["Please wait a minute."])

    def test_name_entry_maps_punctuation_and_speaks_name_changes(self):
        ram = FakeRAM()
        dispatcher(ram)
        name_state(ram)
        reader = DuckStationCardSpeechReader(ram)

        context = (10, NAME_STATE)
        self.assertEqual(
            reader.poll(context), ["Name entry. Enter your name here. Dash."]
        )
        self.assertEqual(
            reader.hint(), "D-pad Select. X Type. Triangle Delete. Select End to finish."
        )
        self.assertEqual(reader.poll(context), [])

        name_state(ram, cursor=1)
        self.assertEqual(reader.poll(context), ["End. Cancel."])
        self.assertEqual(reader.hint(), "X Save. Circle Cancel.")

        name_state(ram, cursor=1, name=b"A")
        self.assertEqual(reader.poll(context), ["Name A."])
        name_state(ram, cursor=2, name=b"A")
        self.assertEqual(reader.poll(context), ["Exclamation mark."])

    def test_save_load_replay_slots_announce_entry_navigation_and_exit(self):
        ram = FakeRAM()
        dispatcher(ram)
        slot_state(ram)
        slot_name(ram, 0, "AAAAAA")
        slot_name(ram, 2, "AB-12")
        reader = DuckStationCardSpeechReader(ram)

        save_context = (11, SLOT_STATE)
        self.assertEqual(reader.poll(save_context), ["Save. AAAAAA."])
        self.assertEqual(reader.hint(), "D-pad Select. X Save.")
        self.assertEqual(reader.poll(save_context), [])

        slot_state(ram, cursor=1)
        self.assertEqual(reader.poll(save_context), ["Empty slot 2."])
        slot_state(ram, cursor=15)
        self.assertEqual(reader.poll(save_context), ["Exit."])
        self.assertEqual(reader.hint(), "D-pad Select. X Exit.")

        slot_state(ram, cursor=0)
        load_context = (12, SLOT_STATE)
        self.assertEqual(reader.poll(load_context), ["Load. AAAAAA."])
        self.assertEqual(reader.hint(), "D-pad Select. X Load.")

        slot_state(ram, cursor=2)
        replay_context = (13, SLOT_STATE)
        self.assertEqual(reader.poll(replay_context), ["Replay. A B Dash 1 2."])
        self.assertEqual(reader.hint(), "D-pad Select. X Replay.")

    def test_invalid_signature_context_and_state_shapes_stay_silent(self):
        ram = FakeRAM()
        reader = DuckStationCardSpeechReader(ram)

        self.assertEqual(reader.poll((2, None)), [])
        self.assertEqual(reader.hint(), "")
        dispatcher(ram)
        self.assertEqual(reader.poll((17, None)), [])
        self.assertEqual(reader.hint(), "")

        self.assertEqual(reader.poll((10, SLOT_STATE)), [])
        self.assertEqual(reader.hint(), "")
        name_state(ram, count=56)
        self.assertEqual(reader.poll((10, NAME_STATE)), [])
        self.assertEqual(reader.hint(), "")

        name_state(ram)
        context = (10, NAME_STATE)
        self.assertEqual(
            reader.poll(context), ["Name entry. Enter your name here. Dash."]
        )
        name_state(ram, count=56)
        self.assertEqual(reader.poll(context), [])
        self.assertEqual(reader.hint(), "")

        slot_state(ram, count=15)
        self.assertEqual(reader.poll((11, SLOT_STATE)), [])
        self.assertEqual(reader.hint(), "")


if __name__ == "__main__":
    unittest.main()
