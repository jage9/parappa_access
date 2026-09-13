"""Hardware-free tests for independent handoff cue mixing."""
import _bootstrap

import struct
import threading
import unittest

from duckstation_audio_output import WasapiCueOutput, mix_pcm16_stereo


def pcm16_stereo(frames):
    return b"".join(struct.pack("<hh", left, right) for left, right in frames)


class FakeAudio:
    paContinue = 0


def make_output(teacher_pcm, handoff_pcm):
    output = WasapiCueOutput.__new__(WasapiCueOutput)
    output.audio = FakeAudio()
    output.pcm = {"CIRCLE": teacher_pcm}
    output.handoff_pcm = handoff_pcm
    output.lock = threading.Lock()
    output.active = "CIRCLE"
    output.offset = 4
    output.generation = 1
    output.handoff_active = False
    output.handoff_offset = 0
    output.handoff_generation = 0
    output.callbacks = []
    output.callback_count = 0
    output.dropped = 0
    output.statuses = {}
    output.samples = 0
    output.closed = False
    output.silence = bytes(4096)
    return output


class HandoffMixTests(unittest.TestCase):
    def test_mixer_sums_short_overlay_and_clips_both_pcm16_limits(self):
        teacher = pcm16_stereo([(32_000, -32_000), (1_000, -1_000)])
        overlay = pcm16_stereo([(10_000, -10_000)])
        mixed = mix_pcm16_stereo(teacher, overlay)
        self.assertEqual(
            [struct.unpack_from("<hh", mixed, offset) for offset in (0, 4)],
            [(32_767, -32_768), (1_000, -1_000)],
        )

    def test_handoff_submission_preserves_teacher_cursor_and_mixes_in_same_callback(self):
        teacher = pcm16_stereo(
            [(1_000, 2_000), (30_000, 1_000), (20_000, 0), (3_000, 0)]
        )
        handoff = pcm16_stereo([(10_000, -6_000), (-25_000, 4_000), (100, 100)])
        output = make_output(teacher, handoff)
        original_active = output.active
        original_offset = output.offset

        result = output.play_handoff()
        self.assertTrue(result["result"])
        self.assertEqual(output.active, original_active)
        self.assertEqual(output.offset, original_offset)

        data, status = output._callback(None, 2, {}, 0)
        self.assertEqual(status, output.audio.paContinue)
        self.assertEqual(
            [struct.unpack_from("<hh", data, offset) for offset in (0, 4)],
            [(32_767, -5_000), (-5_000, 4_000)],
        )
        self.assertEqual(output.active, "CIRCLE")
        self.assertEqual(output.offset, 12)
        self.assertTrue(output.handoff_active)
        self.assertEqual(output.handoff_offset, 8)
        self.assertTrue(output.callbacks[0]["handoff"])
        self.assertEqual(output.callbacks[0]["button"], "CIRCLE")

    def test_callback_without_handoff_preserves_teacher_samples(self):
        teacher = pcm16_stereo([(1_000, -1_000), (2_000, -2_000), (3_000, -3_000)])
        output = make_output(teacher, None)
        output.handoff_pcm = None
        output.handoff_active = False
        output.offset = 0
        data, _ = output._callback(None, 2, {}, 0)
        self.assertEqual(data[:8], teacher[:8])

    def test_mixer_rejects_incomplete_stereo_frames(self):
        with self.assertRaises(ValueError):
            mix_pcm16_stereo(b"\0\0", b"")


if __name__ == "__main__":
    unittest.main(verbosity=2)
