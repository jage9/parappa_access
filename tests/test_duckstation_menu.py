"""Hardware-free coverage for guarded DuckStation menu speech."""
import _bootstrap

import struct
import unittest

from duckstation_menu import (
    CARD_MODE_DISPATCH,
    CARD_MODE_DISPATCH_WORD,
    CARD_OBJECT_POINTER,
    HIGHSCORE_RECORDS,
    HIGHSCORE_STATE,
    MAIN_DESCRIPTOR,
    MAIN_DRAW,
    MAIN_STATE,
    MAPPED_RESOURCE_KEY,
    NAME_KEYBOARD,
    NAME_STATE,
    STAGE_DESCRIPTOR,
    STAGE_DRAW,
    STAGE_INIT,
    STAGE_STATE,
    TITLE_DESCRIPTION,
    TITLE_GUARD_ADDRESS,
    TITLE_GUARD_WORDS,
    MenuReader,
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


def main_menu(ram, *, phase, selected):
    ram.write(
        MAIN_DESCRIPTOR,
        struct.pack(
            "<IIIII", 0x80026794, 0x800264AC, MAIN_DRAW, 0, MAIN_STATE
        ),
    )
    ram.word(MAIN_DRAW, 0x27BDFFE8)
    state = bytearray(0x1C)
    struct.pack_into("<H", state, 0, phase)
    struct.pack_into("<HH", state, 0x0C, selected, 5)
    struct.pack_into("<H", state, 0x18, 0)
    ram.write(MAIN_STATE, state)


def stage_menu(ram, *, selected, progress=(1, 1, 0, 0, 0, 0)):
    ram.word(STAGE_INIT, 0x8C860010)
    ram.word(STAGE_DRAW, 0x27BDFFE8)
    ram.word(STAGE_DRAW + 8, 0x8C840010)
    ram.word(STAGE_DESCRIPTOR + 0x10, STAGE_STATE)
    state = bytearray(0x20)
    struct.pack_into("<h", state, 4, 0)
    struct.pack_into("<hh", state, 8, selected, 8)
    for index, value in enumerate(progress, start=1):
        struct.pack_into("<H", state, 0x0C + index * 2, value)
    ram.write(STAGE_STATE, state)


def highscore_table(ram):
    table = bytearray(0x10)
    struct.pack_into("<hh", table, 0x0C, 6, 3)
    ram.write(HIGHSCORE_STATE, table)
    records = bytearray(6 * 0x40)
    samples = ((b"AAA", 12345), (b"", 0), (b"ZZZ", 900))
    for rank, (name, score) in enumerate(samples):
        offset = rank * 0x10
        records[offset : offset + len(name)] = name
        struct.pack_into("<i", records, offset + 0x0C, score)
    ram.write(HIGHSCORE_RECORDS, records)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class DuckStationMenuTests(unittest.TestCase):
    def test_title_keeps_credits_and_announces_start_menu_separately(self):
        ram = FakeRAM()
        selector = 0x80050000
        ram.write(TITLE_GUARD_ADDRESS, struct.pack("<II", *TITLE_GUARD_WORDS))
        ram.word(selector, 0)
        reader = MenuReader(ram, title_selector_address=selector)

        text = reader.poll()
        self.assertEqual(len(text), 1)
        self.assertTrue(text[0].startswith(TITLE_DESCRIPTION))
        self.assertIn("PaRappa the Rapper, trademark.", text[0])
        self.assertIn("Copyright 1997 Sony Computer Entertainment Inc.", text[0])
        self.assertNotIn("Start and Menu", text[0])
        self.assertTrue(text[0].endswith("Start."))
        self.assertEqual(reader.hint(), "D-pad Left and Right Select. X Confirm.")

        ram.word(selector, 1)
        self.assertEqual(reader.poll(), ["Menu."])

    def test_stage_entry_names_screen_then_navigation_names_new_stage(self):
        ram = FakeRAM()
        clock = Clock()
        reader = MenuReader(ram, clock=clock)

        main_menu(ram, phase=0, selected=3)
        self.assertEqual(reader.poll(), [])
        main_menu(ram, phase=1, selected=3)
        self.assertEqual(reader.poll(), ["Main menu. Stage."])

        clock.now += 2.26
        stage_menu(ram, selected=1)
        self.assertEqual(reader.poll(), ["Stage select. Stage 1. Not cleared."])
        self.assertEqual(reader.hint(), "D-pad Select. X Play.")
        self.assertEqual(reader.poll(), [])

        stage_menu(ram, selected=2)
        self.assertEqual(reader.poll(), ["Stage 2. Not cleared."])

    def test_stage_select_announces_clear_and_cool_progress(self):
        ram = FakeRAM()
        clock = Clock()
        reader = MenuReader(ram, clock=clock)
        main_menu(ram, phase=0, selected=3)
        reader.poll()
        main_menu(ram, phase=1, selected=3)
        reader.poll()
        clock.now += 2.26

        # Progress as recorded in the save: Cool, cleared, unlocked, locked.
        progress = (3, 2, 1, 0, 0, 0)
        stage_menu(ram, selected=1, progress=progress)
        self.assertEqual(
            reader.poll(), ["Stage select. Stage 1. Cleared on Cool."]
        )
        stage_menu(ram, selected=2, progress=progress)
        self.assertEqual(reader.poll(), ["Stage 2. Cleared."])
        stage_menu(ram, selected=3, progress=progress)
        self.assertEqual(reader.poll(), ["Stage 3. Not cleared."])
        # Unknown values fall back to the bare stage name.
        stage_menu(ram, selected=4, progress=(3, 2, 1, 9, 0, 0))
        self.assertEqual(reader.poll(), ["Stage 4."])
        stage_menu(ram, selected=7, progress=(3, 3, 3, 3, 3, 3))
        self.assertEqual(reader.poll(), ["Bonus. KT and the Sunny Funny Band."])
        stage_menu(ram, selected=8, progress=progress)
        self.assertEqual(reader.poll(), ["Exit."])
        self.assertEqual(reader.hint(), "D-pad Select. X Exit.")

    def test_pending_high_scores_does_not_read_a_stale_table_before_modal(self):
        ram = FakeRAM()
        highscore_table(ram)
        clock = Clock()
        reader = MenuReader(ram, clock=clock)

        # A valid but stale table is not sufficient context to announce it.
        self.assertEqual(reader.poll(), [])
        self.assertEqual(reader.hint(), "")

        main_menu(ram, phase=0, selected=3)
        self.assertEqual(reader.poll(), [])
        main_menu(ram, phase=1, selected=3)
        self.assertEqual(reader.poll(), ["Main menu. Stage."])
        main_menu(ram, phase=1, selected=1)
        self.assertEqual(reader.poll(), ["High scores."])
        self.assertEqual(reader.hint(), "X Open.")

        # Selecting High scores only makes it pending. With no live modal
        # context, the old but well-formed table must not be announced.
        clock.now += 2.26
        self.assertEqual(reader.poll(), [])
        self.assertEqual(reader.hint(), "")

    def test_name_entry_requires_a_new_resource_edge_and_guarded_keyboard(self):
        ram = FakeRAM()
        ram.word(CARD_MODE_DISPATCH, CARD_MODE_DISPATCH_WORD)
        ram.word(CARD_OBJECT_POINTER, NAME_STATE)
        ram.word(MAPPED_RESOURCE_KEY, 5)
        state = bytearray(0x22)
        struct.pack_into("<I", state, 0x0C, NAME_KEYBOARD)
        struct.pack_into("<hhh", state, 0x14, 57, 0, 0)
        ram.write(NAME_STATE, state)
        ram.write(NAME_KEYBOARD, b"AB" + bytes(55))
        reader = MenuReader(ram)

        # Attaching while the cached resource is already 5 is not an entry.
        self.assertEqual(reader.poll(), [])

        ram.word(MAPPED_RESOURCE_KEY, 7)
        self.assertEqual(reader.poll(), [])
        ram.word(MAPPED_RESOURCE_KEY, 5)
        self.assertEqual(
            reader.poll(), ["Name entry. Enter your name here. A."]
        )
        self.assertEqual(
            reader.hint(), "D-pad Select. X Type. Triangle Delete. Select End to finish."
        )

        ram.short(NAME_STATE + 0x16, 1)
        self.assertEqual(reader.poll(), ["B."])

    def test_cached_save_question_fields_do_not_activate_card_speech(self):
        ram = FakeRAM()
        reader = MenuReader(ram)
        self.assertEqual(reader.poll(), [])

        # Mode 2 used resource 11/object 0x8007cc50, but resource 11 is also
        # used by mode 21 and the cache can outlive the active prompt.
        ram.word(CARD_MODE_DISPATCH, CARD_MODE_DISPATCH_WORD)
        ram.word(MAPPED_RESOURCE_KEY, 11)
        ram.word(CARD_OBJECT_POINTER, 0x8007CC50)
        self.assertEqual(reader.poll(), [])
        self.assertEqual(reader.hint(), "")

    def test_cached_saved_slot_selector_does_not_announce_on_attach(self):
        ram = FakeRAM()
        slot_state = 0x80048E50
        ram.word(CARD_MODE_DISPATCH, CARD_MODE_DISPATCH_WORD)
        ram.word(MAPPED_RESOURCE_KEY, 7)
        ram.word(CARD_OBJECT_POINTER, slot_state)
        ram.short(slot_state + 0x10, 16)
        ram.short(slot_state + 0x14, 0)
        ram.write(0x8007A590 + 0x5C, b"SAVED\0")
        reader = MenuReader(ram)

        # The cursor shape and selected name can be stale after returning from
        # a card menu; without a live mode/entry guard they are not speech.
        self.assertEqual(reader.poll(), [])
        self.assertEqual(reader.hint(), "")


if __name__ == "__main__":
    unittest.main()
