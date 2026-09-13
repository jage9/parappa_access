import _bootstrap
import unittest

from duckstation_scene_speech import (
    SCENE_TEXT,
    _SCENE_WAIT_SIGNATURES,
    decode_scene_wait,
)


def sample(scene, *, pc=0x8003571C, gpr_ra=0x8003561C, stack_ra=None,
           wait_ra=None, parent_ra=None, sp=0x801FFF18, size=0x70):
    signatures = _SCENE_WAIT_SIGNATURES
    if wait_ra is None:
        wait_ra = signatures[scene][0]
    if parent_ra is None:
        parent_ra = signatures[scene][1]
    if stack_ra is None:
        stack_ra = gpr_ra

    registers = bytearray(128)
    registers[29 * 4:30 * 4] = sp.to_bytes(4, "little")
    registers[31 * 4:32 * 4] = gpr_ra.to_bytes(4, "little")
    stack = bytearray(size)
    for offset, value in ((0x18, stack_ra), (0x30, 0x801C3640),
                          (0x38, wait_ra), (0x68, parent_ra)):
        if offset + 4 <= size:
            stack[offset:offset + 4] = value.to_bytes(4, "little")
    return pc, registers, stack


class DecodeSceneWaitTests(unittest.TestCase):
    def test_stage_one_live_intro_signature(self):
        self.assertEqual(decode_scene_wait(*sample(1)), 1)
        self.assertIn("I need to become a hero!", SCENE_TEXT[1])

    def test_stage_two_live_intro_signature(self):
        self.assertEqual(decode_scene_wait(*sample(2, pc=0x800356D0,
                                                   gpr_ra=0x800355F8)), 2)
        self.assertIn("You guys sit in the back.", SCENE_TEXT[2])

    def test_stage_three_live_intro_signature(self):
        self.assertEqual(decode_scene_wait(*sample(3)), 3)
        self.assertIn("My dad's gonna bite me!", SCENE_TEXT[3])

    def test_post_clear_parent_return_is_not_intro(self):
        self.assertIsNone(decode_scene_wait(*sample(1, parent_ra=0x801C8438)))

    def test_each_part_of_live_wait_signature_is_required(self):
        self.assertIsNone(decode_scene_wait(*sample(1, wait_ra=0x801C791C)))
        self.assertIsNone(decode_scene_wait(*sample(2, parent_ra=0x801C7730)))
        self.assertIsNone(decode_scene_wait(*sample(1, stack_ra=0x800355F8)))

    def test_wait_pc_and_stack_pointer_bounds_are_required(self):
        self.assertIsNone(decode_scene_wait(*sample(1, pc=0x801C8278)))
        self.assertIsNone(decode_scene_wait(*sample(1, sp=0x801FFF94)))
        self.assertIsNone(decode_scene_wait(*sample(1, sp=0x80000002)))

    def test_short_or_unreadable_snapshot_is_rejected(self):
        pc, registers, stack = sample(1)
        self.assertIsNone(decode_scene_wait(pc, registers[:120], stack))
        self.assertIsNone(decode_scene_wait(pc, registers, stack[:0x6C]))

    def test_stage_three_and_four_intro_text(self):
        self.assertEqual(decode_scene_wait(*sample(4,wait_ra=0x801C8318,parent_ra=0x801C8D14)),4)
        self.assertIn("My dad's gonna bite me!", SCENE_TEXT[3])
        self.assertIn("Guaranteed to catch her heart.", SCENE_TEXT[4])

    def test_stage_five_and_six_intro_text(self):
        self.assertEqual(decode_scene_wait(*sample(5,wait_ra=0x801C66B0,parent_ra=0x801C70BC)),5)
        self.assertEqual(decode_scene_wait(*sample(6,wait_ra=0x801C70BC,parent_ra=0x801C7AB4)),6)
        self.assertIn("Full tank.", SCENE_TEXT[5])
        self.assertIn("I gotta believe!", SCENE_TEXT[6])

    def test_ending_key_seven_uses_stage_six_ending_signature(self):
        self.assertEqual(SCENE_TEXT[7], "Ending scene.")
        snapshot = sample(7)
        self.assertEqual(decode_scene_wait(*snapshot), 7)

    def test_later_stage_signatures_require_both_returns(self):
        self.assertIsNone(decode_scene_wait(
            *sample(3, wait_ra=0x801C787C)))
        self.assertIsNone(decode_scene_wait(
            *sample(4, parent_ra=0x801C8438)))
        self.assertIsNone(decode_scene_wait(
            *sample(7, parent_ra=0xDEADBEEF)))


if __name__ == "__main__":
    unittest.main()
