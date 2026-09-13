"""Hardware-free tests for the verified DuckStation card UI context guard."""
import _bootstrap

import struct
import unittest

from duckstation_ui_context import CardContext, decode_card_wait


RAM_BASE = 0x80000000
RAM_SIZE = 0x200000
STACK_POINTER = 0x80010000
CARD_STATE = 0x80123450
CARD_MODE = 11
MODAL_DESCRIPTOR = 0x8005458C
MODAL_STATE = 0x80049278
HIGHSCORE_MODE = 17
HIGHSCORE_GP = 0x8006EA40
CARD_VARIANT_STORE = 0x80019218
CARD_VARIANT_STORE_WORD = 0xAF9002DC
CARD_VARIANT_WORD = 0x8006ED1C

CODE_SIGNATURES = (
    (0x80018FB0, 0x27BDFFC8),
    (0x800190EC, 0x0C00D558),
    (0x80035570, 0x27BDFFE0),
    (0x800356A8, 0x27BDFFE0),
    (0x80035614, 0x0C00D5AA),
    (0x80026B94, 0x27BDFFC8),
    (0x80026DC0, 0x0C00D558),
)


def make_registers(*, s3=0, gp=0, sp=STACK_POINTER, fp=0x80011000, ra=0x8003561C):
    registers = bytearray(128)
    struct.pack_into("<I", registers, 19 * 4, s3)
    struct.pack_into("<I", registers, 28 * 4, gp)
    struct.pack_into("<I", registers, 29 * 4, sp)
    struct.pack_into("<I", registers, 30 * 4, fp)
    struct.pack_into("<I", registers, 31 * 4, ra)
    return bytes(registers)


def make_stack(*, inner_return=0x8003561C, outer_return=0x800190F4,
               mode=CARD_MODE, state=CARD_STATE):
    stack = bytearray(0x40)
    struct.pack_into("<I", stack, 0x18, inner_return)
    struct.pack_into("<I", stack, 0x30, mode)
    struct.pack_into("<I", stack, 0x34, state)
    struct.pack_into("<I", stack, 0x38, outer_return)
    return bytes(stack)


def make_highscore_ram(*, variant=3, gp=HIGHSCORE_GP,
                       variant_store_word=CARD_VARIANT_STORE_WORD):
    registers = make_registers(gp=gp)
    ram = FakeRAM(
        registers=[registers] * 2,
        stack=make_stack(mode=HIGHSCORE_MODE),
    )
    ram.word(CARD_VARIANT_STORE, variant_store_word)
    ram.word(CARD_VARIANT_WORD, variant)
    return ram


class FakeRAM:
    def __init__(self, *, registers=None, pcs=None, cpu_context_verified=True,
                 valid_code=True, stack=None):
        self.data = bytearray(RAM_SIZE)
        self.cpu_context_verified = cpu_context_verified
        self.register_snapshots = list(registers or [make_registers()] * 2)
        self.program_counters = list(pcs or [0x800356D0] * 2)
        self.stack = stack if stack is not None else make_stack()
        self.register_reads = 0
        self.pc_reads = 0

        for address, signature in CODE_SIGNATURES:
            self.word(address, signature if valid_code else 0)
        self.write(STACK_POINTER, self.stack)

    def read(self, address, size):
        offset = address - RAM_BASE
        if not 0 <= offset <= RAM_SIZE - size:
            raise ValueError("read outside fake PS1 RAM")
        return bytes(self.data[offset : offset + size])

    def write(self, address, value):
        offset = address - RAM_BASE
        if not 0 <= offset <= RAM_SIZE - len(value):
            raise ValueError("write outside fake PS1 RAM")
        self.data[offset : offset + len(value)] = value

    def word(self, address, value):
        self.write(address, struct.pack("<I", value))

    def read_registers(self):
        index = min(self.register_reads, len(self.register_snapshots) - 1)
        self.register_reads += 1
        return self.register_snapshots[index]

    def read_program_counter(self):
        index = min(self.pc_reads, len(self.program_counters) - 1)
        self.pc_reads += 1
        return self.program_counters[index]


class DecodeCardWaitTests(unittest.TestCase):
    def test_decodes_the_two_verified_wait_instructions(self):
        registers = make_registers()
        stack = make_stack()

        for pc in (0x800356D0, 0x8003571C):
            with self.subTest(pc=hex(pc)):
                self.assertEqual(
                    decode_card_wait(pc, registers, stack),
                    (CARD_MODE, CARD_STATE),
                )

    def test_rejects_wrong_pc_register_return_or_saved_stack_chain(self):
        registers = make_registers()
        stack = make_stack()
        invalid_frames = (
            (0x800356D4, registers, stack),
            (0x800356D0, make_registers(ra=0x80035620), stack),
            (0x800356D0, registers, make_stack(inner_return=0x80035620)),
            (0x800356D0, registers, make_stack(outer_return=0x800190F0)),
        )

        for index, (pc, frame_registers, frame_stack) in enumerate(invalid_frames):
            with self.subTest(case=index, pc=hex(pc)):
                self.assertIsNone(decode_card_wait(pc, frame_registers, frame_stack))

    def test_rejects_malformed_stack_pointer_and_out_of_range_context(self):
        bad_contexts = (
            (make_registers(sp=STACK_POINTER + 2), make_stack()),
            (make_registers(sp=0x80200000), make_stack()),
            (make_registers(), make_stack(mode=1)),
            (make_registers(), make_stack(state=0x80200000)),
        )

        for index, (registers, stack) in enumerate(bad_contexts):
            with self.subTest(case=index):
                self.assertIsNone(decode_card_wait(0x800356D0, registers, stack))


class CardContextTests(unittest.TestCase):
    def test_non_highscore_card_mode_does_not_require_variant_guard(self):
        ram = FakeRAM()
        context = CardContext(ram)

        self.assertTrue(context.valid_code)
        self.assertEqual(context.poll(), (CARD_MODE, CARD_STATE))
        self.assertEqual(ram.register_reads, 2)
        self.assertEqual(ram.pc_reads, 2)

    def test_accepts_highscore_wait_only_with_verified_variant_three(self):
        ram = make_highscore_ram(variant=3)

        self.assertEqual(
            CardContext(ram).poll(),
            (HIGHSCORE_MODE, CARD_STATE),
        )

    def test_rejects_highscore_wait_for_load_or_replay_variants(self):
        for variant in (0, 1, 2):
            with self.subTest(variant=variant):
                ram = make_highscore_ram(variant=variant)
                self.assertIsNone(CardContext(ram).poll())

    def test_rejects_highscore_wait_with_wrong_gp_or_variant_store_code(self):
        cases = (
            make_highscore_ram(gp=HIGHSCORE_GP + 4),
            make_highscore_ram(variant_store_word=CARD_VARIANT_STORE_WORD ^ 1),
        )

        for index, ram in enumerate(cases):
            with self.subTest(case=index):
                self.assertIsNone(CardContext(ram).poll())

    def test_requires_pinned_code_and_verified_cpu_context(self):
        for ram in (
            FakeRAM(valid_code=False),
            FakeRAM(cpu_context_verified=False),
        ):
            with self.subTest(valid_code=ram.data[0x18FB0:0x18FB4].hex(),
                              verified=ram.cpu_context_verified):
                context = CardContext(ram)
                self.assertIsNone(context.poll())
                self.assertEqual(ram.register_reads, 0)
                self.assertEqual(ram.pc_reads, 0)

    def test_rejects_wrong_live_pc_and_stale_saved_stack(self):
        cases = (
            FakeRAM(pcs=[0x800356D4, 0x800356D4]),
            FakeRAM(stack=make_stack(outer_return=0x800190F0)),
        )

        for ram in cases:
            with self.subTest(pc=ram.program_counters[0], stack=ram.stack.hex()):
                self.assertIsNone(CardContext(ram).poll())

    def test_rejects_cpu_state_that_changes_during_stack_read(self):
        changed_fp = make_registers(fp=0x80011004)
        cases = (
            (make_registers(), changed_fp, [0x800356D0, 0x800356D0]),
            (make_registers(), make_registers(), [0x800356D0, 0x8003571C]),
        )

        for index, (first, second, pcs) in enumerate(cases):
            with self.subTest(case=index, pcs=pcs):
                ram = FakeRAM(registers=[first, second], pcs=pcs)
                self.assertIsNone(CardContext(ram).poll())

    def test_recognizes_and_clears_modal_context(self):
        ram = FakeRAM(
            registers=[make_registers(s3=6)] * 2,
            stack=make_stack(outer_return=0x80026DC8, state=MODAL_DESCRIPTOR),
        )
        ram.word(MODAL_DESCRIPTOR + 0x10, MODAL_STATE)
        context = CardContext(ram)

        self.assertIsNone(context.poll())
        self.assertEqual(context.modal, (6, MODAL_STATE))

        ram.cpu_context_verified = False
        self.assertIsNone(context.poll())
        self.assertIsNone(context.modal)


if __name__ == "__main__":
    unittest.main(verbosity=2)
