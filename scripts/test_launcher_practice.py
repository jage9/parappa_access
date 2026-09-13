from pathlib import Path
from tempfile import TemporaryDirectory
import io
import threading
import time
import unittest
from unittest.mock import Mock, patch
import wave

import launcher_practice
from duckstation_cues import (
    BUTTONS, PAN_POSITIONS, _apply_prepared_volume,
    _make_placeholder_handoff_wav, preprocess_wav,
)


def _wav(value):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        wav.writeframes((int(value).to_bytes(2, "little", signed=True)) * 2205)
    return stream.getvalue()


def _wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


class FakeOutput:
    def __init__(self, device, wavs, handoff):
        self.device = device
        self.wavs = wavs
        self.handoff = handoff
        self.played = []
        self.closed = False

    def play(self, button):
        if self.closed:
            raise RuntimeError("play after close")
        self.played.append(button)

    def play_handoff(self):
        if self.closed:
            raise RuntimeError("play after close")
        self.played.append("handoff")

    def stop(self):
        pass

    def close(self):
        self.closed = True


class LauncherPracticeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "sounds").mkdir()
        for index, button in enumerate(BUTTONS, 1):
            (self.root / "sounds" / f"{button.lower()}.wav").write_bytes(_wav(index * 1000))

    def tearDown(self):
        self.temp.cleanup()

    def _sounds(self, **kwargs):
        return launcher_practice.PracticeSounds(
            self.root, "Chosen device", True, 150, **kwargs)

    def test_start_is_async_and_only_latest_request_plays_after_loading(self):
        entered = threading.Event()
        release = threading.Event()

        def resolve(_preference):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test did not release device lookup")
            return "Resolved device"

        outputs = []

        def make_output(device, wavs, handoff):
            output = FakeOutput(device, wavs, handoff)
            outputs.append(output)
            return output

        sounds = self._sounds()
        with patch.object(launcher_practice.audio_devices, "resolve_preference", side_effect=resolve), \
                patch.object(launcher_practice, "WasapiCueOutput", side_effect=make_output):
            sounds.start()
            self.assertTrue(entered.wait(1), "background worker did not start promptly")
            self.assertTrue(sounds.play("X")["result"])
            self.assertTrue(sounds.play("R1")["result"])
            self.assertEqual(outputs, [])
            release.set()
            self.assertTrue(_wait_for(lambda: outputs and outputs[0].played == ["R1"]))
            self.assertEqual(outputs[0].device, "Resolved device")
            sounds.close()
            self.assertTrue(outputs[0].closed)

    def test_preparation_is_centered_handoff_panned_buttons_and_writes_nothing(self):
        before = {path.relative_to(self.root) for path in self.root.rglob("*")}
        captured = []
        factory_entered = threading.Event()

        def make_output(device, wavs, handoff):
            captured.append((device, wavs, handoff))
            factory_entered.set()
            return FakeOutput(device, wavs, handoff)

        sounds = self._sounds()
        with patch.object(launcher_practice.audio_devices, "resolve_preference", return_value="Chosen device"), \
                patch.object(launcher_practice, "WasapiCueOutput", side_effect=make_output):
            sounds.start()
            self.assertTrue(factory_entered.wait(2))
            self.assertTrue(_wait_for(lambda: sounds.ready))
            device, wavs, handoff = captured[0]
            self.assertEqual(device, "Chosen device")
            self.assertEqual(set(wavs), set(BUTTONS))
            for index, button in enumerate(BUTTONS, 1):
                source = (self.root / "sounds" / f"{button.lower()}.wav").read_bytes()
                expected = _apply_prepared_volume(
                    preprocess_wav(source, pan=PAN_POSITIONS[button]), 150).wav_bytes
                self.assertEqual(wavs[button], expected)
            expected_handoff = _apply_prepared_volume(
                preprocess_wav(_make_placeholder_handoff_wav()), 150).wav_bytes
            self.assertEqual(handoff, expected_handoff)
            self.assertEqual(
                {path.relative_to(self.root) for path in self.root.rglob("*")}, before)
            sounds.close()

    def test_close_during_output_open_cancels_pending_play_and_closes_from_worker(self):
        entered = threading.Event()
        release = threading.Event()
        outputs = []

        def make_output(device, wavs, handoff):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test did not release output construction")
            output = FakeOutput(device, wavs, handoff)
            outputs.append(output)
            return output

        sounds = self._sounds()
        with patch.object(launcher_practice.audio_devices, "resolve_preference", return_value="Chosen device"), \
                patch.object(launcher_practice, "WasapiCueOutput", side_effect=make_output):
            sounds.start()
            self.assertTrue(entered.wait(2))
            self.assertTrue(sounds.play("CIRCLE")["result"])
            sounds.close(wait=False)
            release.set()
            sounds.close(wait=True)
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0].played, [])
        self.assertTrue(outputs[0].closed)

    def test_failure_is_saved_and_reported_once(self):
        callback = Mock()
        sounds = self._sounds(on_error=callback)
        with patch.object(launcher_practice.audio_devices, "resolve_preference", return_value=None):
            sounds.start()
            self.assertTrue(_wait_for(lambda: sounds.error is not None))
            self.assertIn("Choose an audio device", sounds.error)
            self.assertEqual(callback.call_count, 1)
            self.assertFalse(sounds.play("X")["result"])
            sounds.close()


if __name__ == "__main__":
    unittest.main()
