"""Hardware-free tests for the verified DuckStation title-wait guard."""

import struct
import unittest

from duckstation_ui_context import decode_title_wait


STACK_POINTER = 0x801FFF00
TITLE_STATE = 0x801C3640
TITLE_RETURN = 0x801C4D74
WAIT_FRAMES = (
    (0x800356D0, 0x800355F8),
    (0x8003571C, 0x8003561C),
)


def sample(selection, *, pc=0x8003571C, live_ra=0x8003561C,
           saved_ra=None, state=TITLE_STATE, caller=TITLE_RETURN,
           sp=STACK_POINTER):
    if saved_ra is None:
        saved_ra = live_ra
    registers = bytearray(128)
    struct.pack_into("<I", registers, 29 * 4, sp)
    struct.pack_into("<I", registers, 31 * 4, live_ra)

    stack = bytearray(0x54)
    struct.pack_into("<I", stack, 0x18, saved_ra)
    struct.pack_into("<I", stack, 0x34, state)
    struct.pack_into("<I", stack, 0x38, caller)
    struct.pack_into("<I", stack, 0x50, selection)
    return pc, bytes(registers), bytes(stack)


class DecodeTitleWaitTests(unittest.TestCase):
    def test_returns_selection_address_for_both_title_choices(self):
        for selection in (0, 1):
            for pc, ra in WAIT_FRAMES:
                with self.subTest(selection=selection, pc=hex(pc), ra=hex(ra)):
                    self.assertEqual(
                        decode_title_wait(
                            *sample(selection, pc=pc, live_ra=ra)
                        ),
                        STACK_POINTER + 0x50,
                    )

    def test_rejects_main_practice_and_stage_wait_chains(self):
        unrelated_callers = {
            "main": 0x801C4DC4,
            "practice": 0x800277DC,
            "stage": 0x801C787C,
        }
        for screen, caller in unrelated_callers.items():
            with self.subTest(screen=screen):
                self.assertIsNone(decode_title_wait(*sample(0, caller=caller)))

    def test_rejects_invalid_stack_pointer_bounds_and_alignment(self):
        invalid_pointers = (
            0x7FFFFFFC,
            0x80000002,
            0x80200000 - 0x50,
        )
        for sp in invalid_pointers:
            with self.subTest(sp=hex(sp)):
                self.assertIsNone(decode_title_wait(*sample(0, sp=sp)))

    def test_rejects_invalid_live_or_saved_return_address(self):
        self.assertIsNone(decode_title_wait(*sample(0, live_ra=0x80035620)))
        self.assertIsNone(decode_title_wait(*sample(0, saved_ra=0x80035620)))

    def test_rejects_invalid_wait_pc(self):
        self.assertIsNone(decode_title_wait(*sample(0, pc=0x800356D4)))

    def test_requires_title_state_and_binary_selection_value(self):
        self.assertIsNone(decode_title_wait(*sample(0, state=0x801C3644)))
        self.assertIsNone(decode_title_wait(*sample(2)))
        self.assertIsNone(decode_title_wait(*sample(0xFFFFFFFF)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
