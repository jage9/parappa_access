import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock, patch
import wave

import launcher_preview
from duckstation_cues import preprocess_wav, _apply_prepared_volume


def _wav(frames=441):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\x10\x27' * frames)
    return stream.getvalue()


def _wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


class FakeOutput:
    def __init__(self, device, wavs):
        self.device = device
        self.wavs = wavs
        self.played = []
        self.closed = False
        self.close_count = 0
        self.lock = threading.Lock()

    def play(self, cue):
        with self.lock:
            if self.closed:
                raise RuntimeError('play after close')
            self.played.append(cue)

    def stop(self):
        pass

    def close(self):
        with self.lock:
            self.close_count += 1
            self.closed = True


class OutputFactory:
    def __init__(self, entered=None, release=None):
        self.entered = entered
        self.release = release
        self.outputs = []
        self.lock = threading.Lock()

    def __call__(self, device, wavs):
        if self.entered is not None:
            self.entered.set()
        if self.release is not None and not self.release.wait(3):
            raise RuntimeError('test did not release blocked output factory')
        output = FakeOutput(device, wavs)
        with self.lock:
            self.outputs.append(output)
        return output


class VolumePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'sounds').mkdir()
        self.source = _wav()
        (self.root / 'sounds' / 'x.wav').write_bytes(self.source)
        self.menu = SimpleNamespace(audio_output='Chosen device', cue_volume=100)

    def tearDown(self):
        launcher_preview.close_preview(self.menu)
        self.temp.cleanup()

    def _patched(self, factory):
        return (
            patch.object(launcher_preview, 'ROOT', self.root),
            patch.object(launcher_preview.audio_devices, 'resolve_preference',
                         side_effect=lambda preference: preference),
            patch.object(launcher_preview, 'WasapiCueOutput', side_effect=factory),
        )

    def test_prepare_is_silent_and_preview_reuses_centered_precomputed_stream(self):
        factory = OutputFactory()
        root_patch, device_patch, output_patch = self._patched(factory)
        with root_patch, device_patch, output_patch:
            launcher_preview.prepare_preview(self.menu)
            self.assertTrue(_wait_for(lambda: len(factory.outputs) == 1))
            output = factory.outputs[0]
            self.assertEqual(output.device, 'Chosen device')
            self.assertEqual(output.played, [])

            expected = {
                f'VOLUME_{volume}': _apply_prepared_volume(
                    preprocess_wav(self.source, pan=None), volume).wav_bytes
                for volume in range(0, 201, 10)
            }
            self.assertEqual(output.wavs, expected)

            self.menu.cue_volume = 130
            launcher_preview.preview_volume(self.menu)
            self.assertTrue(_wait_for(lambda: len(output.played) == 1))
            self.assertEqual(output.played, ['VOLUME_130'])
            self.menu.cue_volume = 140
            launcher_preview.preview_volume(self.menu)
            self.assertTrue(_wait_for(lambda: len(output.played) == 2))
            self.assertEqual(output.played[-1], 'VOLUME_140')
            self.assertEqual(len(factory.outputs), 1)

        launcher_preview.close_preview(self.menu)
        self.assertTrue(output.closed)
        self.assertEqual(output.close_count, 1)

    def test_latest_volume_wins_while_stream_is_opening(self):
        entered = threading.Event()
        release = threading.Event()
        factory = OutputFactory(entered, release)
        root_patch, device_patch, output_patch = self._patched(factory)
        with root_patch, device_patch, output_patch:
            self.menu.cue_volume = 80
            launcher_preview.preview_volume(self.menu)
            self.assertTrue(entered.wait(2))

            for volume in (110, 150, 190):
                self.menu.cue_volume = volume
                launcher_preview.preview_volume(self.menu)
            launcher_preview.prepare_preview(self.menu)  # Returning from the device picker
            # Silent warmup must preserve the pending audible device/volume request.
            # Calls above return while the worker is still blocked opening audio.
            release.set()
            self.assertTrue(_wait_for(lambda: bool(factory.outputs)
                                      and len(factory.outputs[0].played) == 1))
            self.assertEqual(factory.outputs[0].played, ['VOLUME_190'])
        launcher_preview.close_preview(self.menu)

    def test_device_or_sound_stat_change_rebuilds_and_closes_old_stream(self):
        factory = OutputFactory()
        root_patch, device_patch, output_patch = self._patched(factory)
        with root_patch, device_patch, output_patch:
            launcher_preview.prepare_preview(self.menu)
            self.assertTrue(_wait_for(lambda: len(factory.outputs) == 1))
            first = factory.outputs[0]

            self.menu.audio_output = 'Other device'
            self.menu.cue_volume = 120
            launcher_preview.preview_volume(self.menu)
            self.assertTrue(_wait_for(lambda: len(factory.outputs) == 2))
            second = factory.outputs[1]
            self.assertTrue(first.closed)
            self.assertEqual(first.close_count, 1)
            self.assertEqual(second.device, 'Other device')
            self.assertTrue(_wait_for(lambda: second.played == ['VOLUME_120']))

            new_source = _wav(frames=442)
            (self.root / 'sounds' / 'x.wav').write_bytes(new_source)
            self.menu.cue_volume = 150
            launcher_preview.preview_volume(self.menu)
            self.assertTrue(_wait_for(lambda: len(factory.outputs) == 3))
            third = factory.outputs[2]
            self.assertTrue(second.closed)
            self.assertEqual(third.device, 'Other device')
            self.assertTrue(_wait_for(lambda: third.played == ['VOLUME_150']))
            self.assertEqual(third.wavs['VOLUME_150'], _apply_prepared_volume(
                preprocess_wav(new_source, pan=None), 150).wav_bytes)

        launcher_preview.close_preview(self.menu)
        self.assertTrue(third.closed)

    def test_warmup_error_is_deferred_until_user_requests_preview(self):
        callback = Mock()
        root_patch = patch.object(launcher_preview, 'ROOT', self.root)
        device_patch = patch.object(
            launcher_preview.audio_devices, 'resolve_preference', return_value=None)
        output_patch = patch.object(launcher_preview, 'WasapiCueOutput')
        with root_patch, device_patch, output_patch:
            launcher_preview.prepare_preview(self.menu, on_error=callback)
            worker = self.menu._cue_preview_worker
            self.assertTrue(_wait_for(lambda: worker.error is not None))
            callback.assert_not_called()

            launcher_preview.preview_volume(self.menu, on_error=callback)
            self.assertTrue(_wait_for(lambda: callback.called))
            callback.assert_called_once_with()
            error = launcher_preview.take_preview_error(self.menu)
            self.assertIn('Choose an audio device', error)
            self.assertIsNone(launcher_preview.take_preview_error(self.menu))

    def test_volume_request_during_failed_warmup_notifies_once(self):
        entered = threading.Event()
        release = threading.Event()
        callback = Mock()

        def resolve_while_blocked(preference):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('test did not release device lookup')
            return None

        root_patch = patch.object(launcher_preview, 'ROOT', self.root)
        device_patch = patch.object(
            launcher_preview.audio_devices, 'resolve_preference',
            side_effect=resolve_while_blocked)
        output_patch = patch.object(launcher_preview, 'WasapiCueOutput')
        with root_patch, device_patch, output_patch:
            launcher_preview.prepare_preview(self.menu, on_error=callback)
            self.assertTrue(entered.wait(2))
            self.menu.cue_volume = 120
            launcher_preview.preview_volume(self.menu, on_error=callback)
            release.set()
            self.assertTrue(_wait_for(lambda: callback.called))
            callback.assert_called_once_with()
            self.assertIn('Choose an audio device',
                          launcher_preview.take_preview_error(self.menu))

    def test_close_during_device_open_prevents_late_play(self):
        entered = threading.Event()
        release = threading.Event()
        factory = OutputFactory(entered, release)
        root_patch, device_patch, output_patch = self._patched(factory)
        with root_patch, device_patch, output_patch:
            launcher_preview.preview_volume(self.menu)
            self.assertTrue(entered.wait(2))
            worker = self.menu._cue_preview_worker
            closer = threading.Thread(target=launcher_preview.close_preview,
                                      args=(self.menu,))
            closer.start()
            self.assertTrue(_wait_for(lambda: worker.closed))
            release.set()
            closer.join(3)
            self.assertFalse(closer.is_alive())
            self.assertEqual(len(factory.outputs), 1)
            output = factory.outputs[0]
            self.assertTrue(output.closed)
            self.assertEqual(output.close_count, 1)
            self.assertEqual(output.played, [])
            self.assertFalse(hasattr(self.menu, '_cue_preview_worker'))


if __name__ == '__main__':
    unittest.main()
