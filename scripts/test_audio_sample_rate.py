"""Hardware-free tests for cue PCM resampling and output-rate selection."""

import io
import math
import struct
import sys
import types
import unittest
import wave
from unittest.mock import patch

from duckstation_audio_output import WasapiCueOutput, render_pcm


def make_wav(samples, *, sample_rate=44100, channels=1):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setparams((channels, 2, sample_rate, 0, "NONE", "not compressed"))
        wav.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))
    return stream.getvalue()


class FakeStream:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.closed = False

    def get_output_latency(self):
        return 0.02

    def start_stream(self):
        self.started = True

    def stop_stream(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FakePyAudio:
    def __init__(self, supported_rates):
        self.supported_rates = set(supported_rates)
        self.format_checks = []
        self.open_args = None
        self.stream = None
        self.terminated = False

    def get_device_count(self):
        return 1

    def get_device_info_by_index(self, index):
        return {
            "index": index,
            "name": "Behringer USB Audio",
            "hostApi": 0,
            "isLoopbackDevice": False,
            "maxOutputChannels": 2,
            "defaultSampleRate": 48000.0,
        }

    def get_host_api_info_by_index(self, index):
        return {"index": index, "type": 13}

    def is_format_supported(self, rate, **kwargs):
        self.format_checks.append((rate, kwargs))
        if rate not in self.supported_rates:
            raise ValueError("unsupported rate", -9997)
        return True

    def open(self, **kwargs):
        self.open_args = kwargs
        self.stream = FakeStream()
        return self.stream

    def terminate(self):
        self.terminated = True


def fake_audio_module(device, creations):
    module = types.ModuleType("pyaudiowpatch")
    module.paWASAPI = 13
    module.paInt16 = 8
    module.paContinue = 0

    def create_device():
        creations.append(device)
        return device

    module.PyAudio = create_device
    return module


class AudioSampleRateTests(unittest.TestCase):
    def test_44100_hz_stereo_pcm_bytes_are_unchanged(self):
        source_pcm = b"".join(
            struct.pack("<hh", left, right)
            for left, right in ((0, 10), (1000, -1000), (-32768, 32767))
        )
        wav_bytes = make_wav(
            [sample for frame in ((0, 10), (1000, -1000), (-32768, 32767))
             for sample in frame],
            sample_rate=44100,
            channels=2,
        )

        self.assertEqual(render_pcm(wav_bytes), source_pcm)
        self.assertEqual(render_pcm(wav_bytes, output_rate=44100), source_pcm)

    def test_44100_hz_is_preferred_when_the_device_supports_it(self):
        device = FakePyAudio({44100, 48000})
        module = fake_audio_module(device, [])
        with patch.dict(sys.modules, {"pyaudiowpatch": module}):
            output = WasapiCueOutput("Behringer USB Audio", {"X": make_wav([0, 1])})

        try:
            self.assertEqual([rate for rate, _ in device.format_checks], [44100])
            self.assertEqual(device.open_args["rate"], 44100)
            self.assertEqual(output.manifest["rate"], 44100)
        finally:
            output.close()

    def test_48000_hz_resample_preserves_duration_channels_and_pitch(self):
        input_rate = 44100
        output_rate = 48000
        frequency = 440
        frames = input_rate // 10
        samples = [round(20000 * math.sin(2 * math.pi * frequency * i / input_rate))
                   for i in range(frames)]

        pcm = render_pcm(make_wav(samples, sample_rate=input_rate), output_rate)
        output_frames = len(pcm) // 4
        self.assertEqual(output_frames, round(frames * output_rate / input_rate))
        self.assertAlmostEqual(output_frames / output_rate, frames / input_rate, places=5)

        left = [struct.unpack_from("<h", pcm, i * 4)[0] for i in range(output_frames)]
        right = [struct.unpack_from("<h", pcm, i * 4 + 2)[0] for i in range(output_frames)]
        self.assertEqual(left, right)
        positive_crossings = sum(a <= 0 < b for a, b in zip(left, left[1:]))
        estimated_frequency = positive_crossings / (output_frames / output_rate)
        self.assertAlmostEqual(estimated_frequency, frequency, delta=1)

    def test_unsupported_44100_uses_verified_device_default_for_all_cues(self):
        device = FakePyAudio({48000})
        creations = []
        module = fake_audio_module(device, creations)
        wave_44100 = make_wav([0, 1000, -1000, 0], sample_rate=44100)
        wave_22050 = make_wav([0, 2000, -2000, 0], sample_rate=22050, channels=2)
        buttons = ("CIRCLE", "X", "SQUARE", "TRIANGLE", "L1", "R1")
        prepared = {button: wave_22050 if index % 2 else wave_44100
                    for index, button in enumerate(buttons)}
        handoff = make_wav([0, 500, 1000, 0], sample_rate=44100, channels=2)

        with patch.dict(sys.modules, {"pyaudiowpatch": module}):
            output = WasapiCueOutput("Behringer USB Audio", prepared, handoff)

        self.assertEqual(creations, [device])
        self.assertEqual([rate for rate, _ in device.format_checks], [44100, 48000])
        self.assertTrue(all(check[1]["output_device"] == 0 for check in device.format_checks))
        self.assertTrue(all(check[1]["output_channels"] == 2 for check in device.format_checks))
        self.assertTrue(all(check[1]["output_format"] == module.paInt16 for check in device.format_checks))
        self.assertEqual(device.open_args["rate"], 48000)
        self.assertEqual(device.open_args["channels"], 2)
        self.assertEqual(output.manifest["rate"], 48000)
        self.assertTrue(device.stream.started)
        for button, wav_bytes in prepared.items():
            self.assertEqual(output.pcm[button], render_pcm(wav_bytes, 48000))
        self.assertEqual(output.handoff_pcm, render_pcm(handoff, 48000))

        output.close()
        self.assertTrue(device.stream.stopped)
        self.assertTrue(device.stream.closed)
        self.assertTrue(device.terminated)

    def test_unsupported_rates_terminate_audio_without_opening_stream(self):
        device = FakePyAudio(set())
        module = fake_audio_module(device, [])

        with patch.dict(sys.modules, {"pyaudiowpatch": module}):
            with self.assertRaisesRegex(RuntimeError, "supports none of 44100 or 48000 Hz"):
                WasapiCueOutput("Behringer USB Audio", {"X": make_wav([1])})

        self.assertEqual([rate for rate, _ in device.format_checks], [44100, 48000])
        self.assertIsNone(device.open_args)
        self.assertTrue(device.terminated)


if __name__ == "__main__":
    unittest.main(verbosity=2)
