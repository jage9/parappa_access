"""Hardware-free tests for the DuckStation cue WAV conversion path."""
import _bootstrap

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from duckstation_cues import (
    CueSounds,
    CuePreparationError,
    PAN_POSITIONS,
    _apply_prepared_volume,
    _make_placeholder_handoff_wav,
    load_handoff_wav,
    parse_pcm_wav,
    preprocess_wav,
)


ROOT = Path(__file__).resolve().parents[1]


def make_wav(samples, *, channels=1, bits=16, sample_rate=22050):
    """Build a canonical PCM WAV from per-frame signed sample tuples."""
    if channels == 1:
        samples = [(sample,) for sample in samples]
    sample_width = bits // 8
    pcm = bytearray()
    for frame in samples:
        if len(frame) != channels:
            raise ValueError("sample frame has the wrong channel count")
        for sample in frame:
            if bits == 16:
                pcm.extend(struct.pack("<h", sample))
            elif bits == 24:
                encoded = sample & 0xFFFFFF
                pcm.extend((encoded & 0xFF, (encoded >> 8) & 0xFF, encoded >> 16))
            else:
                raise ValueError("test helper supports PCM16/PCM24")

    block_align = channels * sample_width
    fmt = struct.pack(
        "<HHIIHH",
        1,
        channels,
        sample_rate,
        sample_rate * block_align,
        block_align,
        bits,
    )
    padding = b"\0" if len(pcm) & 1 else b""
    return b"".join(
        (
            b"RIFF",
            struct.pack("<I", 36 + len(pcm) + len(padding)),
            b"WAVEfmt ",
            struct.pack("<I", 16),
            fmt,
            b"data",
            struct.pack("<I", len(pcm)),
            pcm,
            padding,
        )
    )


def samples_from_wav(data):
    info = parse_pcm_wav(data)
    if info.bits_per_sample != 16:
        raise ValueError("expected prepared PCM16")
    result = []
    cursor = info.data_offset
    for _ in range(info.frames):
        result.append(struct.unpack_from("<" + "h" * info.channels, data, cursor))
        cursor += info.block_align
    return info, result


class CueConversionTests(unittest.TestCase):
    def test_unpanned_pcm16_is_preserved_and_leading_silence_is_counted(self):
        source = make_wav([0, 0, 1000, -2000])
        prepared = preprocess_wav(source)
        self.assertEqual(prepared.wav_bytes, source)
        self.assertEqual(prepared.output_info.frames, 4)
        self.assertEqual(prepared.leading_silence_frames, 2)

    def test_pcm24_reduction_uses_signed_half_away_rounding(self):
        values = [0, 127, 128, -127, -128, 8_388_607, -8_388_608]
        prepared = preprocess_wav(make_wav(values, bits=24, sample_rate=8000))
        info, actual = samples_from_wav(prepared.wav_bytes)
        self.assertEqual(info.bits_per_sample, 16)
        self.assertEqual(info.channels, 1)
        self.assertEqual([frame[0] for frame in actual], [0, 0, 1, 0, -1, 32767, -32768])
        self.assertEqual(prepared.source_info.bits_per_sample, 24)

    def test_equal_power_pan_centers_mono_and_zeroes_the_far_side_at_extreme(self):
        left = preprocess_wav(make_wav([2000, -2000]), pan=-1.0)
        left_info, left_samples = samples_from_wav(left.wav_bytes)
        self.assertEqual(left_info.channels, 2)
        self.assertEqual(left_samples, [(2000, 0), (-2000, 0)])

        center = preprocess_wav(make_wav([(1000, 3000)], channels=2), pan=0.0)
        _, center_samples = samples_from_wav(center.wav_bytes)
        self.assertEqual(center_samples, [(1414, 1414)])

    def test_invalid_pan_and_non_pcm_input_are_rejected(self):
        source = make_wav([1000])
        with self.assertRaises(ValueError):
            preprocess_wav(source, pan=1.1)

        compressed = bytearray(source)
        struct.pack_into("<H", compressed, 20, 3)
        with self.assertRaises(CuePreparationError):
            preprocess_wav(bytes(compressed))

    def test_all_current_repository_cues_prepare_without_audio_hardware(self):
        for button in ("CIRCLE", "X", "SQUARE", "TRIANGLE", "L1", "R1"):
            with self.subTest(button=button):
                source = (ROOT / "sounds" / f"{button.lower()}.wav").read_bytes()
                prepared = preprocess_wav(source, pan=PAN_POSITIONS[button])
                self.assertEqual(prepared.output_info.bits_per_sample, 16)
                self.assertEqual(prepared.output_info.channels, 2)
                # Users replace these WAVs; bit-depth conversion is covered
                # by fixed synthetic fixtures, not a per-button file list.


class CueVolumeTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "logs").mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_cue_volume_", dir=ROOT / "logs")
        self.session_root = Path(self.temp_dir.name)
        self.pan_patch = patch("duckstation_cues._load_pan_setting", return_value=(False, None))
        self.pan_patch.start()

    def tearDown(self):
        self.pan_patch.stop()
        self.temp_dir.cleanup()

    def make_cues(self, name, **kwargs):
        return CueSounds(ROOT, self.session_root / name, enabled=False, **kwargs)

    def test_default_volume_preserves_all_six_prepared_wavs_and_records_setting(self):
        cues = self.make_cues("identity")
        try:
            self.assertEqual(cues.manifest["settings"]["volume_percent"], 100)
            for button in ("CIRCLE", "X", "SQUARE", "TRIANGLE", "L1", "R1"):
                with self.subTest(button=button):
                    source = (ROOT / "sounds" / f"{button.lower()}.wav").read_bytes()
                    expected = preprocess_wav(source).wav_bytes
                    exported = (cues.output_dir / f"{button.lower()}.wav").read_bytes()
                    self.assertEqual(exported, expected)
        finally:
            cues.close()

    def test_zero_volume_silences_all_six_cues_without_changing_wav_metadata(self):
        cues = self.make_cues("mute", volume_percent=0)
        try:
            self.assertEqual(cues.manifest["settings"]["volume_percent"], 0)
            for button in ("CIRCLE", "X", "SQUARE", "TRIANGLE", "L1", "R1"):
                with self.subTest(button=button):
                    source = (ROOT / "sounds" / f"{button.lower()}.wav").read_bytes()
                    expected_info = preprocess_wav(source).output_info
                    data = (cues.output_dir / f"{button.lower()}.wav").read_bytes()
                    info, frames = samples_from_wav(data)
                    self.assertEqual(info, expected_info)
                    self.assertTrue(all(not any(frame) for frame in frames))
                    self.assertEqual(
                        cues.manifest["sounds"][button]["leading_silence_frames"],
                        info.frames,
                    )
        finally:
            cues.close()

    def test_increase_clips_pcm16_and_gain_follows_conversion_and_panning(self):
        prepared = preprocess_wav(make_wav([1000, -1000, 101, -101, 32767, -32768]))
        increased = _apply_prepared_volume(prepared, 150)
        _, actual = samples_from_wav(increased.wav_bytes)
        self.assertEqual(
            [frame[0] for frame in actual],
            [1500, -1500, 152, -152, 32767, -32768],
        )

        clipped = _apply_prepared_volume(
            preprocess_wav(make_wav([20000, -20000, 32767, -32768])), 200
        )
        _, actual = samples_from_wav(clipped.wav_bytes)
        self.assertEqual([frame[0] for frame in actual], [32767, -32768, 32767, -32768])

        # 2304 in PCM24 converts to 9, then centered panning rounds each side
        # to 6, then 50% volume rounds it to 3. Applying volume first would
        # produce 4 after the same panning step.
        converted_and_panned = preprocess_wav(
            make_wav([2304], bits=24, sample_rate=8000), pan=0.0
        )
        self.assertEqual(samples_from_wav(converted_and_panned.wav_bytes)[1], [(6, 6)])
        scaled_after_pan = _apply_prepared_volume(converted_and_panned, 50)
        self.assertEqual(samples_from_wav(scaled_after_pan.wav_bytes)[1], [(3, 3)])

    def test_invalid_volume_is_rejected_before_creating_a_session(self):
        with self.assertRaises(TypeError):
            CueSounds(ROOT, self.session_root / "positional", False,
                      "output", False, 50)
        for invalid in (True, False, 1.5, "50", None):
            with self.subTest(value=invalid):
                with self.assertRaises(TypeError):
                    CueSounds(ROOT, self.session_root / "invalid-type", enabled=False,
                              volume_percent=invalid)
        for invalid in (-1, 201):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    CueSounds(ROOT, self.session_root / "invalid-range", enabled=False,
                              volume_percent=invalid)
        self.assertFalse((self.session_root / "invalid-type").exists())
        self.assertFalse((self.session_root / "invalid-range").exists())
        self.assertFalse((self.session_root / "positional").exists())

    def test_scaled_handoff_and_fallback_buffers_match_wavs_passed_to_wasapi(self):
        outputs = []

        class FakeOutput:
            def __init__(self, output_name, prepared_wavs, handoff_wav=None):
                self.prepared_wavs = prepared_wavs
                self.handoff_wav = handoff_wav
                outputs.append(self)

            @property
            def manifest(self):
                return {"name": "fake shared output"}

            def play_handoff(self):
                return {"result": True, "status": "submitted"}

            def close(self):
                pass

        with patch("duckstation_audio_output.WasapiCueOutput", FakeOutput):
            cues = CueSounds(ROOT, self.session_root / "scaled-playback", enabled=True,
                             handoff_enabled=True, volume_percent=50)
            try:
                self.assertEqual(cues.manifest["settings"]["volume_percent"], 50)
                output = outputs[0]
                for button in ("CIRCLE", "X", "SQUARE", "TRIANGLE", "L1", "R1"):
                    with self.subTest(button=button):
                        exported = (cues.output_dir / f"{button.lower()}.wav").read_bytes()
                        self.assertEqual(output.prepared_wavs[button], exported)
                        source = (ROOT / "sounds" / f"{button.lower()}.wav").read_bytes()
                        expected = _apply_prepared_volume(preprocess_wav(source), 50).wav_bytes
                        self.assertEqual(exported, expected)
                        self.assertEqual(
                            cues.manifest["sounds"][button]["output_sha256"],
                            hashlib.sha256(exported).hexdigest(),
                        )
                        # WinMM fallback uses these retained in-memory WAV buffers.
                        fallback = cues._buffers[button][0].raw[:len(exported)]
                        self.assertEqual(fallback, exported)

                handoff = (cues.output_dir / "handoff.wav").read_bytes()
                self.assertEqual(output.handoff_wav, handoff)
                full_volume = self.make_cues("handoff-reference", handoff_enabled=True)
                try:
                    source = (full_volume.output_dir / "handoff.wav").read_bytes()
                    expected = _apply_prepared_volume(preprocess_wav(source), 50).wav_bytes
                    self.assertEqual(handoff, expected)
                finally:
                    full_volume.close()
            finally:
                cues.close()

    def test_diagnostics_metadata_mode_does_not_create_session_or_wav_copies(self):
        session = self.session_root / "metadata-only"
        cues = CueSounds(ROOT, session, enabled=False, handoff_enabled=True, export_wavs=False)
        try:
            self.assertFalse(session.exists())
            self.assertIsNone(cues.output_dir)
            self.assertIsNone(cues.manifest["prepared_directory"])
            self.assertTrue(all(row["prepared_path"] is None for row in cues.manifest["sounds"].values()))
            self.assertIsNone(cues.manifest["handoff"]["prepared_path"])
        finally:
            cues.close()

    def test_no_export_keeps_prepared_audio_available_to_the_live_backend(self):
        outputs = []

        class FakeOutput:
            def __init__(self, output_name, prepared_wavs, handoff_wav=None):
                self.prepared_wavs=prepared_wavs
                self.handoff_wav=handoff_wav
                outputs.append(self)

            @property
            def manifest(self):
                return {"name":"fake shared output"}

            def close(self):
                pass

        session=self.session_root/"live-no-export"
        with patch("duckstation_cues._load_pan_setting",return_value=(False,None)), \
             patch("duckstation_audio_output.WasapiCueOutput",FakeOutput):
            cues=CueSounds(ROOT,session,enabled=True,handoff_enabled=True,export_wavs=False)
            try:
                self.assertFalse(session.exists())
                self.assertEqual(set(outputs[0].prepared_wavs),{"CIRCLE","X","SQUARE","TRIANGLE","L1","R1"})
                self.assertEqual(outputs[0].prepared_wavs["X"],preprocess_wav((ROOT/"sounds"/"x.wav").read_bytes()).wav_bytes)
                source=(ROOT/"sounds"/"handoff.wav").read_bytes()
                self.assertEqual(outputs[0].handoff_wav,preprocess_wav(source).wav_bytes)
            finally:
                cues.close()


class HandoffCueTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "logs").mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_handoff_", dir=ROOT / "logs")
        self.session_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_handoff_is_disabled_by_default_without_export_or_playback(self):
        cues = CueSounds(ROOT, self.session_dir, enabled=False)
        try:
            result = cues.play_handoff()
            self.assertFalse(result["result"])
            self.assertEqual(result["status"], "disabled")
            self.assertFalse(cues.manifest["settings"]["handoff_enabled"])
            self.assertFalse(cues.manifest["handoff"]["enabled"])
            self.assertFalse((cues.output_dir / "handoff.wav").exists())
        finally:
            cues.close()

    def test_enabled_handoff_exports_the_replaceable_centered_60ms_sound(self):
        cues = CueSounds(ROOT, self.session_dir, enabled=False, handoff_enabled=True)
        try:
            path = cues.output_dir / "handoff.wav"
            info, frames = samples_from_wav(path.read_bytes())
            self.assertEqual(info.sample_rate, 44_100)
            self.assertIn(info.channels, (1, 2))
            self.assertEqual(info.bits_per_sample, 16)
            self.assertAlmostEqual(info.duration_ms, 60.0, delta=0.1)
            self.assertTrue(frames)
            self.assertTrue(all(len(set(frame)) == 1 for frame in frames))
            self.assertTrue(any(frame[0] != 0 for frame in frames))

            handoff = cues.manifest["handoff"]
            self.assertTrue(cues.manifest["settings"]["handoff_enabled"])
            self.assertTrue(handoff["enabled"])
            self.assertEqual(handoff["source"], "repository_file")
            self.assertEqual(handoff["source_path"], "sounds/handoff.wav")
            self.assertEqual(handoff["prepared_path"], "cue-wavs/handoff.wav")
            self.assertEqual(handoff["frames"], 2_646)
            self.assertTrue(handoff["centered"])
            result = cues.play_handoff()
            self.assertFalse(result["result"])
            self.assertEqual(result["status"], "disabled")
        finally:
            cues.close()

    def test_enabled_handoff_is_passed_to_the_existing_output_and_delegated(self):
        outputs = []

        class FakeOutput:
            def __init__(self, output_name, prepared_wavs, handoff_wav=None):
                self.output_name = output_name
                self.prepared_wavs = prepared_wavs
                self.handoff_wav = handoff_wav
                self.play_handoff_calls = 0
                outputs.append(self)

            @property
            def manifest(self):
                return {"name": "fake shared output"}

            def play_handoff(self):
                self.play_handoff_calls += 1
                return {"result": True, "status": "submitted"}

            def close(self):
                pass

        with patch("duckstation_audio_output.WasapiCueOutput", FakeOutput):
            cues = CueSounds(ROOT, self.session_dir, enabled=True, handoff_enabled=True)
            try:
                self.assertEqual(len(outputs), 1)
                self.assertEqual(set(outputs[0].prepared_wavs), set(("CIRCLE", "X", "SQUARE", "TRIANGLE", "L1", "R1")))
                self.assertEqual(
                    outputs[0].handoff_wav,
                    (cues.output_dir / "handoff.wav").read_bytes(),
                )
                self.assertEqual(cues.manifest["backend"]["name"], "fake shared output")
                self.assertEqual(cues.play_handoff(), {"result": True, "status": "submitted"})
                self.assertEqual(outputs[0].play_handoff_calls, 1)
            finally:
                cues.close()


class HandoffSourceTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "logs").mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_handoff_source_", dir=ROOT / "logs")
        self.session_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_handoff_file_uses_generated_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            wav, source_path, source_type=load_handoff_wav(directory)
        self.assertEqual(wav,_make_placeholder_handoff_wav())
        self.assertIsNone(source_path)
        self.assertEqual(source_type,"generated_placeholder")

    def test_repository_handoff_file_is_loaded_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/"sounds"/"handoff.wav"
            path.parent.mkdir()
            expected=make_wav([100,-100],sample_rate=22050)
            path.write_bytes(expected)
            actual,source_path,source_type=load_handoff_wav(root)
        self.assertEqual(actual,expected)
        self.assertEqual(source_path,"sounds/handoff.wav")
        self.assertEqual(source_type,"repository_file")

    def test_handoff_setting_can_be_off_while_button_cues_remain_enabled(self):
        outputs = []

        class FakeOutput:
            def __init__(self, output_name, prepared_wavs, handoff_wav=None):
                self.handoff_wav = handoff_wav
                self.play_handoff_calls = 0
                outputs.append(self)

            @property
            def manifest(self):
                return {"name": "fake shared output"}

            def play_handoff(self):
                self.play_handoff_calls += 1
                return {"result": True, "status": "submitted"}

            def close(self):
                pass

        with patch("duckstation_audio_output.WasapiCueOutput", FakeOutput):
            cues = CueSounds(ROOT, self.session_dir, enabled=True, handoff_enabled=False)
            try:
                self.assertTrue(cues.enabled)
                self.assertFalse(cues.manifest["settings"]["handoff_enabled"])
                self.assertIsNone(outputs[0].handoff_wav)
                self.assertFalse((cues.output_dir / "handoff.wav").exists())
                result = cues.play_handoff()
                self.assertFalse(result["result"])
                self.assertEqual(result["status"], "disabled")
                self.assertEqual(outputs[0].play_handoff_calls, 0)
            finally:
                cues.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
