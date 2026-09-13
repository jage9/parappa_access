"""Hardware-free tests for Scene 0 opening and title wait contexts."""
import _bootstrap

import struct
import unittest

from test_duckstation_ui_context import FakeRAM, STACK_POINTER, make_registers
from duckstation_ui_context import CardContext, decode_opening_wait, decode_title_wait


WAIT_PC = 0x8003571C
WAIT_RAS = (0x8003561C, 0x800355F8)
SCENE_POINTER = 0x801C3640
OPENING_RETURN = 0x801C44AC
TITLE_RETURN = 0x801C4D74
TITLE_CODE = bytes.fromhex("1000a58f1516070c")
WAIT_CALL = 0x0C00D558


def make_stack(*, live_ra=WAIT_RAS[0], scene_pointer=SCENE_POINTER,
               wait_return=OPENING_RETURN, state=SCENE_POINTER, size=0x70):
    stack = bytearray(size)
    for offset, value in ((0x18, live_ra), (0x34, scene_pointer),
                          (0x38, wait_return), (0x50, state)):
        if offset + 4 <= len(stack):
            struct.pack_into("<I", stack, offset, value)
    return bytes(stack)


def make_opening_sample(*, pc=WAIT_PC, ra=WAIT_RAS[0], sp=STACK_POINTER,
                        scene_pointer=SCENE_POINTER,
                        wait_return=OPENING_RETURN, state=SCENE_POINTER,
                        size=0x70):
    registers = make_registers(sp=sp, ra=ra)
    stack = make_stack(live_ra=ra, scene_pointer=scene_pointer,
                       wait_return=wait_return, state=state, size=size)
    return pc, registers, stack


def make_context_ram(*, pc=WAIT_PC, ra=WAIT_RAS[0], scene_pointer=SCENE_POINTER,
                     wait_return=OPENING_RETURN, state=SCENE_POINTER):
    sample_stack = make_stack(live_ra=ra, scene_pointer=scene_pointer,
                              wait_return=wait_return, state=state)
    ram = FakeRAM(registers=[make_registers(ra=ra)] * 2,
                  pcs=[pc, pc], stack=sample_stack)
    ram.write(0x801C4D20, TITLE_CODE)
    ram.word(0x801C44A4, WAIT_CALL)
    ram.word(0x801C4D6C, WAIT_CALL)
    return ram


class DecodeOpeningWaitTests(unittest.TestCase):
    def test_accepts_both_live_vsync_return_variants(self):
        for ra in WAIT_RAS:
            with self.subTest(ra=hex(ra)):
                self.assertTrue(decode_opening_wait(*make_opening_sample(ra=ra)))

    def test_rejects_incorrect_pc_or_truncated_snapshot(self):
        self.assertFalse(decode_opening_wait(
            *make_opening_sample(pc=0x80035714)))
        self.assertFalse(decode_opening_wait(
            *make_opening_sample(size=0x53)))
        pc, registers, stack = make_opening_sample()
        self.assertFalse(decode_opening_wait(pc, registers[:127], stack))

    def test_rejects_bad_stack_pointer_or_live_return_chain(self):
        cases = (
            make_opening_sample(sp=STACK_POINTER + 2),
            make_opening_sample(sp=0x80200000),
            make_opening_sample(ra=0x80035620),
            make_opening_sample(ra=WAIT_RAS[0], wait_return=TITLE_RETURN),
        )
        for index, sample in enumerate(cases):
            with self.subTest(case=index):
                self.assertFalse(decode_opening_wait(*sample))

    def test_rejects_wrong_scene_or_secondary_state_pointer(self):
        cases = (
            make_opening_sample(scene_pointer=SCENE_POINTER + 4),
            make_opening_sample(state=SCENE_POINTER + 4),
        )
        for index, sample in enumerate(cases):
            with self.subTest(case=index):
                self.assertFalse(decode_opening_wait(*sample))

    def test_opening_stack_never_matches_title_wait(self):
        self.assertIsNone(decode_title_wait(*make_opening_sample()))


class OpeningCardContextTests(unittest.TestCase):
    def test_accepts_opening_with_live_stack_and_static_call_guard(self):
        ram = make_context_ram()
        context = CardContext(ram)

        context.poll()

        self.assertTrue(context.opening)
        self.assertIsNone(context.title_selector)

    def test_rejects_opening_when_either_static_guard_changes(self):
        bad_opening_call = make_context_ram()
        bad_opening_call.word(0x801C44A4, WAIT_CALL ^ 1)
        bad_scene_guard = make_context_ram()
        bad_scene_guard.write(0x801C4D20, b"\0" * len(TITLE_CODE))

        for ram in (bad_opening_call, bad_scene_guard):
            with self.subTest(ram=ram):
                context = CardContext(ram)
                context.poll()
                self.assertFalse(context.opening)

    def test_title_wait_stays_separate_and_passes_its_own_code_guard(self):
        title_stack = make_stack(wait_return=TITLE_RETURN, state=1)
        ram = FakeRAM(registers=[make_registers(ra=WAIT_RAS[0])] * 2,
                      pcs=[WAIT_PC, WAIT_PC], stack=title_stack)
        ram.write(0x801C4D20, TITLE_CODE)
        ram.word(0x801C4D6C, WAIT_CALL)
        context = CardContext(ram)

        context.poll()

        self.assertFalse(context.opening)
        self.assertEqual(context.title_selector, STACK_POINTER + 0x50)


if __name__ == "__main__":
    unittest.main(verbosity=2)
