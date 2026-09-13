"""Integration tests for title-card scene recognition in CardContext."""

import struct
import unittest
from unittest.mock import patch

from test_duckstation_ui_context import FakeRAM, STACK_POINTER, make_registers
from duckstation_ui_context import CardContext


WAIT_PC = 0x8003571C
LIVE_WAIT_RETURN = 0x8003561C
SCENE_POINTER = 0x801C3640
CALL_JAL = 0x0C00D558
CARD_ENTRY_BYTES = bytes.fromhex("d0ffbd272400b5af")

STAGE3_PROFILE_ENTRY = 0x801C70F4
STAGE3_CARD_ENTRY = 0x801C6E54
STAGE3_WAIT_RA = 0x801C6F10
STAGE3_CALLER_RA = 0x801C790C

STAGE6_PROFILE_ENTRY = 0x801C72A0
STAGE6_CARD_ENTRY = 0x801C7000
STAGE6_WAIT_RA = 0x801C70BC
STAGE6_ENDING_CALLER_RA = 0x801C7EB4


def jal(target):
    return 0x0C000000 | ((target >> 2) & 0x03FFFFFF)


def make_scene_ram(*, wait_ra, caller_ra, profile_entry, card_entry,
                   scene_pointer=SCENE_POINTER, caller_argument=0,
                   caller_argument_offset=-12,
                   intro_jal=None, wait_jal=CALL_JAL):
    stack = bytearray(0x70)
    for offset, value in (
        (0x18, LIVE_WAIT_RETURN),
        (0x30, scene_pointer),
        (0x38, wait_ra),
        (0x68, caller_ra),
    ):
        struct.pack_into("<I", stack, offset, value)

    ram = FakeRAM(
        registers=[make_registers(ra=LIVE_WAIT_RETURN)] * 2,
        pcs=[WAIT_PC, WAIT_PC],
        stack=bytes(stack),
    )
    ram.word(profile_entry, 0x27BDFFC8)
    ram.write(card_entry, CARD_ENTRY_BYTES)
    ram.word(wait_ra - 8, wait_jal)
    ram.word(caller_ra + caller_argument_offset, caller_argument)
    ram.word(caller_ra - 8, jal(card_entry) if intro_jal is None else intro_jal)
    return ram


def make_stage3_ram(**kwargs):
    return make_scene_ram(
        wait_ra=STAGE3_WAIT_RA,
        caller_ra=STAGE3_CALLER_RA,
        profile_entry=STAGE3_PROFILE_ENTRY,
        card_entry=STAGE3_CARD_ENTRY,
        caller_argument=0x00003021,
        caller_argument_offset=-12,
        **kwargs,
    )


def make_stage6_ending_ram(**kwargs):
    return make_scene_ram(
        wait_ra=STAGE6_WAIT_RA,
        caller_ra=STAGE6_ENDING_CALLER_RA,
        profile_entry=STAGE6_PROFILE_ENTRY,
        card_entry=STAGE6_CARD_ENTRY,
        caller_argument=0x2406FFFF,
        caller_argument_offset=-4,
        **kwargs,
    )


class SceneContextTests(unittest.TestCase):
    def test_accepts_stage_three_live_stack_and_overlay_chain(self):
        context = CardContext(make_stage3_ram())

        context.poll()

        self.assertEqual(context.scene, 3)

    def test_rejects_wrong_stage_three_caller_return(self):
        ram = make_stage3_ram()
        ram.word(STACK_POINTER + 0x68, 0x801C8ED4)

        context = CardContext(ram)
        context.poll()

        self.assertIsNone(context.scene)

    def test_rejects_wrong_scene_state_pointer(self):
        context = CardContext(make_stage3_ram(scene_pointer=0x801C3644))

        context.poll()

        self.assertIsNone(context.scene)

    def test_rejects_wrong_card_marker_and_intro_jal(self):
        bad_marker = make_stage3_ram()
        bad_marker.write(STAGE3_CARD_ENTRY, b"\0" * len(CARD_ENTRY_BYTES))
        bad_jal = make_stage3_ram(intro_jal=0x0C00D559)

        for ram in (bad_marker, bad_jal):
            with self.subTest(ram=ram):
                with patch("duckstation_scene_speech.decode_scene_wait", return_value=3):
                    context = CardContext(ram)
                    context.poll()
                self.assertIsNone(context.scene)

    def test_rejects_wrong_stage_profile_entry_word(self):
        ram = make_stage3_ram()
        ram.word(STAGE3_PROFILE_ENTRY, 0)

        with patch("duckstation_scene_speech.decode_scene_wait", return_value=3):
            context = CardContext(ram)
            context.poll()

        self.assertIsNone(context.scene)

    def test_rejects_stage_three_call_with_nonzero_argument_zero(self):
        ram = make_stage3_ram()
        ram.word(STAGE3_CALLER_RA - 12, 0x24060001)

        with patch("duckstation_scene_speech.decode_scene_wait", return_value=3):
            context = CardContext(ram)
            context.poll()

        self.assertIsNone(context.scene)

    def test_accepts_ending_live_signature_and_minus_one_guard(self):
        context = CardContext(make_stage6_ending_ram())
        context.poll()

        self.assertEqual(context.scene, 7)

    def test_rejects_ending_without_minus_one_delay_slot(self):
        ram = make_stage6_ending_ram()
        ram.word(STAGE6_ENDING_CALLER_RA - 4, 0x00003021)

        context = CardContext(ram)
        context.poll()

        self.assertIsNone(context.scene)


if __name__ == "__main__":
    unittest.main(verbosity=2)
