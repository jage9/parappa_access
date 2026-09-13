import struct
import unittest
from unittest.mock import patch

import duckstation_handoff as handoff


def make_sample(native, target, marker, swap, tick, second=True):
    return {
        "native": native,
        "target": target,
        "second": second,
        "swap": swap,
        "marker": marker,
        "tick": tick,
    }


def live_wait_samples(start_native=3989, stop_native=3997, start_target=3990,
                      start_swap=1202, start_tick=1000, marker_from=3992):
    """Model the observed second-wait cadence: one sample every two VBlanks."""
    for index, native in enumerate(range(start_native, stop_native + 1, 2)):
        target = start_target + 2 * index
        swap = start_swap + index
        tick = start_tick + 2 * index
        marker = target >= marker_from
        yield make_sample(native, target, marker, swap, tick)


class HandoffFramesTests(unittest.TestCase):
    def collect(self, samples):
        frames = handoff.HandoffFrames()
        events = []
        for sample in samples:
            event = frames.feed(sample)
            if event is not None:
                events.append(event)
        return frames, events

    def test_live_second_wait_sequence_emits_first_visible_frame_once(self):
        # Observed second waits are native 3989/3991/3993/3995/3997 at
        # targets 3990/3992/3994/3996/3998. A two-frame sample step is normal.
        _, events = self.collect(live_wait_samples())

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], {
            "native_vsync": 3997,
            "swap": 1206,
            "tick": 1008,
            "source_tick": 1002,
            "source_target": 3992,
        })

    def test_entering_midphrase_with_marker_already_set_is_silent(self):
        samples = live_wait_samples(start_native=500, stop_native=514,
                                    start_target=800, start_swap=20,
                                    start_tick=9000, marker_from=800)

        _, events = self.collect(samples)

        self.assertEqual(events, [])

    def test_skipped_render_target_does_not_create_a_handoff(self):
        samples = [
            make_sample(3989, 3990, False, 1202, 1000),
            # Native cadence is still valid, but one observed render target is missing.
            make_sample(3991, 3994, True, 1204, 1002),
            make_sample(3993, 3996, True, 1205, 1004),
            make_sample(3995, 3998, True, 1206, 1006),
        ]

        _, events = self.collect(samples)

        self.assertEqual(events, [])

    def test_native_jump_of_three_cancels_pending_handoff(self):
        samples = [
            make_sample(3989, 3990, False, 1202, 1000),
            make_sample(3991, 3992, True, 1203, 1002),
            make_sample(3994, 3994, True, 1204, 1004),
            make_sample(3996, 3996, True, 1205, 1006),
            make_sample(3998, 3998, True, 1206, 1008),
        ]

        _, events = self.collect(samples)

        self.assertEqual(events, [])

    def test_tick_reset_cancels_pending_handoff(self):
        samples = [
            make_sample(3989, 3990, False, 1202, 1000),
            make_sample(3991, 3992, True, 1203, 1002),
            make_sample(3993, 3994, True, 1204, 500),
            make_sample(3995, 3996, True, 1205, 502),
            make_sample(3997, 3998, True, 1206, 504),
        ]

        _, events = self.collect(samples)

        self.assertEqual(events, [])

    def test_wrong_swap_count_does_not_replay_late(self):
        samples = [
            make_sample(3989, 3990, False, 1202, 1000),
            make_sample(3991, 3992, True, 1203, 1002),
            make_sample(3993, 3994, True, 1204, 1004),
            make_sample(3995, 3996, True, 1205, 1006),
            make_sample(3997, 3998, True, 1205, 1008),
            make_sample(3999, 4000, True, 1206, 1010),
        ]

        _, events = self.collect(samples)

        self.assertEqual(events, [])

    def test_inactive_observer_cancels_pending_handoff(self):
        state = bytes(0xB0)
        ram = object()
        observer = handoff.HandoffObserver(ram)
        samples = [
            make_sample(3989, 3990, False, 1202, 1000),
            make_sample(3991, 3992, True, 1203, 1002),
            make_sample(3993, 3994, True, 1204, 1004),
            make_sample(3995, 3996, True, 1205, 1006),
            make_sample(3997, 3998, True, 1206, 1008),
        ]
        clock = iter(range(1_000_000, 1_000_010))
        with patch.object(handoff, "read_wait", side_effect=samples) as read_wait, \
                patch.object(handoff.time, "perf_counter_ns", side_effect=lambda: next(clock)):
            self.assertEqual(observer.poll(state, 1), (None, samples[0]))
            self.assertEqual(observer.poll(state, 1), (None, samples[1]))
            self.assertIsNotNone(observer.frames.pending)

            self.assertEqual(observer.poll(state, 1, active=False), (None, None))
            self.assertIsNone(observer.frames.pending)

            results = [observer.poll(state, 1) for _ in samples[2:]]

        self.assertEqual(read_wait.call_count, len(samples))
        self.assertTrue(all(event is None for event, _ in results))

    def test_separate_marker_edges_can_arm_two_handoffs(self):
        first = list(live_wait_samples())
        second = list(live_wait_samples(start_native=3999, stop_native=4007,
                                        start_target=4000, start_swap=1207,
                                        start_tick=1010, marker_from=4002))

        _, events = self.collect(first + second)

        self.assertEqual([(event["native_vsync"], event["swap"]) for event in events],
                         [(3997, 1206), (4007, 1211)])


class ReadWaitTests(unittest.TestCase):
    class CoherentRAM:
        def __init__(self, state, *, pc=None, ra=None, target=3992, native=3991,
                     swap=1203, caller=None):
            self.state = state
            self.pc = handoff.WAIT_PCS[1] if pc is None else pc
            self.sp = 0x80100000
            self.registers = bytearray(128)
            struct.pack_into("<I", self.registers, 16, target)
            struct.pack_into("<I", self.registers, 116, self.sp)
            struct.pack_into("<I", self.registers, 124,
                             handoff.SECOND_WAIT if ra is None else ra)
            self.stack = bytearray(0x40)
            struct.pack_into("<I", self.stack, 0x38,
                             handoff.WAIT_CALLERS[1] if caller is None else caller)
            self.native = native
            self.swap = swap

        def read_registers(self):
            return bytes(self.registers)

        def read_program_counter(self):
            return self.pc

        def read(self, address, size):
            if address == self.sp:
                return bytes(self.stack[:size])
            if address == 0x80057034:
                return struct.pack("<I", self.native)
            if address == 0x8009658C:
                return struct.pack("<I", self.swap)
            if address == 0x801C3640:
                return self.state[:size]
            raise AssertionError(f"Unexpected RAM read at {address:#x}")

    @staticmethod
    def state_bytes():
        state = bytearray(0xB0)
        struct.pack_into("<h", state, 0x8A, 1)
        struct.pack_into("<h", state, 0x9E, 0)
        struct.pack_into("<h", state, 0x7A, 1)
        struct.pack_into("<I", state, 12, 1002)
        return bytes(state)

    def test_accepts_a_coherent_second_wait_sample(self):
        state = self.state_bytes()
        ram = self.CoherentRAM(state)

        sample = handoff.read_wait(ram, state, 1)

        self.assertEqual(sample, {
            "native": 3991,
            "target": 3992,
            "second": True,
            "swap": 1203,
            "marker": True,
            "tick": 1002,
        })

    def test_rejects_wrong_stage_pc_or_caller(self):
        state = self.state_bytes()
        wrong_pc = self.CoherentRAM(state, pc=0x80012345)
        wrong_caller = self.CoherentRAM(state, caller=0x80000000)

        self.assertIsNone(handoff.read_wait(wrong_pc, state, 1))
        self.assertIsNone(handoff.read_wait(self.CoherentRAM(state), state, 2))
        self.assertIsNone(handoff.read_wait(wrong_caller, state, 1))

    def test_stage6_accepts_runtime_caller_and_rejects_static_candidate(self):
        state = self.state_bytes()
        self.assertIsNotNone(handoff.read_wait(self.CoherentRAM(state, caller=0x801c7930), state, 6))
        self.assertIsNone(handoff.read_wait(self.CoherentRAM(state, caller=0x801c7e24), state, 6))

    def test_experimental_stages_require_their_own_wait_callers(self):
        state = self.state_bytes()
        for stage, caller in ((3, 0x801c7784), (4, 0x801c8b8c), (5, 0x801c6f34)):
            with self.subTest(stage=stage):
                self.assertIsNotNone(handoff.read_wait(self.CoherentRAM(state, caller=caller), state, stage))
                self.assertIsNone(handoff.read_wait(self.CoherentRAM(state), state, stage))
                self.assertNotIn(stage, handoff.VISUALLY_VERIFIED_STAGES)

    def test_rejects_native_frame_outside_the_wait_target(self):
        state = self.state_bytes()
        ram = self.CoherentRAM(state, native=3993)

        self.assertIsNone(handoff.read_wait(ram, state, 1))


if __name__ == "__main__":
    unittest.main()
