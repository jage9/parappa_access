"""Hardware-free tests for the verified Practice wait-stack decoder."""

import struct
import unittest

from duckstation_ui_context import decode_practice_wait


RAM_STACK = 0x801FFEA8
STATE = 0x801C3640
WAIT_PCS = (0x800356D0, 0x8003571C)
WAIT_RAS = (0x800355F8, 0x8003561C)

# Direct returns following `jal 0x80035560` in the captured Practice body.
# The first three appeared in the DuckStation runtime capture; 0x80027EA0 is
# the fourth call site confirmed by the matching resident disassembly.
DIRECT_RETURNS = (0x800277DC, 0x800279DC, 0x80027D34, 0x80027EA0)

# Return addresses after Practice's `jal 0x800276EC` calls. In the nested
# helper wait frame, its own wait return is 0x8002773C at stack +0x38.
HELPER_RETURNS = (0x80027854, 0x80027D9C, 0x80027E58, 0x80027E80)
HELPER_WAIT_RETURN = 0x8002773C


def make_registers(*, sp=RAM_STACK, ra=0x8003561C):
    registers = bytearray(128)
    struct.pack_into("<I", registers, 29 * 4, sp)
    struct.pack_into("<I", registers, 31 * 4, ra)
    return bytes(registers)


def make_stack(*, inner_ra=0x8003561C, caller=0x80027D34,
               state=STATE, helper_state=STATE, helper_caller=0x80027854,
               size=0x70):
    stack = bytearray(size)
    for offset, value in (
        (0x18, inner_ra),
        (0x34, state),
        (0x38, caller),
        (0x54, helper_state),
        (0x58, helper_caller),
    ):
        if offset + 4 <= size:
            struct.pack_into("<I", stack, offset, value)
    return bytes(stack)


class DecodePracticeWaitTests(unittest.TestCase):
    def test_decodes_direct_wait_frames_seen_in_runtime_capture(self):
        for pc in WAIT_PCS:
            for ra in WAIT_RAS:
                for caller in DIRECT_RETURNS:
                    with self.subTest(pc=hex(pc), ra=hex(ra), caller=hex(caller)):
                        self.assertTrue(
                            decode_practice_wait(
                                pc, make_registers(ra=ra),
                                make_stack(inner_ra=ra, caller=caller),
                            )
                        )

    def test_decodes_nested_common_helper_wait_frames(self):
        for pc in WAIT_PCS:
            for ra in WAIT_RAS:
                for caller in HELPER_RETURNS:
                    with self.subTest(pc=hex(pc), ra=hex(ra), caller=hex(caller)):
                        self.assertTrue(
                            decode_practice_wait(
                                pc, make_registers(ra=ra),
                                make_stack(
                                    inner_ra=ra,
                                    caller=HELPER_WAIT_RETURN,
                                    helper_caller=caller,
                                ),
                            )
                        )

    def test_rejects_stage_card_and_card_manager_wait_contexts(self):
        # The captured Stage 1 card/scene loop shares the state pointer and
        # wait helper, but returns to the overlay loop rather than Practice.
        for caller in (0x801C4D74, 0x800190F4, 0x80026DC8):
            with self.subTest(caller=hex(caller)):
                self.assertFalse(
                    decode_practice_wait(
                        0x800356D0, make_registers(),
                        make_stack(caller=caller),
                    )
                )

    def test_rejects_wrong_direct_or_nested_callers(self):
        invalid_frames = (
            make_stack(caller=0x80027D30),
            make_stack(caller=HELPER_WAIT_RETURN, helper_caller=0x801C4D74),
            make_stack(caller=HELPER_WAIT_RETURN, helper_state=0x801C4D74),
            make_stack(state=0x801C4D74),
        )
        for index, stack in enumerate(invalid_frames):
            with self.subTest(case=index):
                self.assertFalse(
                    decode_practice_wait(0x800356D0, make_registers(), stack)
                )

    def test_requires_the_live_ra_to_match_the_saved_wait_ra(self):
        self.assertFalse(
            decode_practice_wait(
                0x800356D0,
                make_registers(ra=0x80035620),
                make_stack(inner_ra=0x8003561C),
            )
        )
        self.assertFalse(
            decode_practice_wait(
                0x800356D0,
                make_registers(ra=0x8003561C),
                make_stack(inner_ra=0x800355F8),
            )
        )

    def test_requires_a_known_wait_pc(self):
        self.assertFalse(
            decode_practice_wait(
                0x800356D4, make_registers(), make_stack()
            )
        )

    def test_requires_an_aligned_in_ram_stack_pointer(self):
        for sp in (RAM_STACK + 2, 0x7FFFFFFC, 0x801FFFC4, 0x80200000):
            with self.subTest(sp=hex(sp)):
                self.assertFalse(
                    decode_practice_wait(
                        0x800356D0, make_registers(sp=sp), make_stack()
                    )
                )

    def test_rejects_truncated_register_or_nested_stack_snapshot(self):
        registers = make_registers()
        self.assertFalse(
            decode_practice_wait(0x800356D0, registers[:124], make_stack())
        )
        self.assertFalse(
            decode_practice_wait(0x800356D0, registers, make_stack(size=0x3F))
        )
        self.assertFalse(
            decode_practice_wait(
                0x800356D0,
                registers,
                make_stack(caller=HELPER_WAIT_RETURN, size=0x5B),
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
