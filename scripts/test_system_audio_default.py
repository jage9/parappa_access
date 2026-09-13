from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import audio_devices
from audio_devices import AudioOutput


def mock_pyaudio(pa):
    module = ModuleType('pyaudiowpatch')
    module.paWASAPI = 13
    module.PyAudio = Mock(return_value=pa)
    return module


class SystemAudioDefaultTests(unittest.TestCase):
    def test_uses_wasapi_default_and_ignores_duckstation_setting(self):
        pa = Mock()
        pa.get_host_api_info_by_type.return_value = {'defaultOutputDevice': 4}
        pa.get_device_info_by_index.return_value = {'name': 'System Speakers'}
        outputs = [
            AudioOutput('System Speakers', 'endpoint-system', 'System Speakers [Loopback]'),
            AudioOutput('Emulator Speakers', 'endpoint-emulator', 'Emulator Speakers [Loopback]'),
        ]

        with TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / 'tools/research/duckstation-stock/portable/settings.ini'
            config.parent.mkdir(parents=True)
            config.write_text('[Audio]\nOutputDevice=endpoint-emulator\n', encoding='utf-8')
            with patch.object(audio_devices, 'ROOT', root), \
                    patch.object(audio_devices, 'list_outputs', return_value=outputs), \
                    patch.dict(sys.modules, {'pyaudiowpatch': mock_pyaudio(pa)}):
                self.assertEqual(audio_devices.system_default_device(), 'System Speakers')
                self.assertEqual(audio_devices.current_device(), 'Emulator Speakers')

        pa.get_host_api_info_by_type.assert_called_once_with(13)
        pa.get_device_info_by_index.assert_called_once_with(4)
        pa.terminate.assert_called_once_with()

    def test_returns_none_when_wasapi_has_no_default_output(self):
        pa = Mock()
        pa.get_host_api_info_by_type.return_value = {'defaultOutputDevice': -1}
        with patch.dict(sys.modules, {'pyaudiowpatch': mock_pyaudio(pa)}), \
                patch.object(audio_devices, 'list_outputs') as list_outputs:
            self.assertIsNone(audio_devices.system_default_device())

        pa.get_device_info_by_index.assert_not_called()
        pa.terminate.assert_called_once_with()
        list_outputs.assert_not_called()

    def test_default_must_be_an_exact_supported_output(self):
        pa = Mock()
        pa.get_host_api_info_by_type.return_value = {'defaultOutputDevice': 2}
        pa.get_device_info_by_index.return_value = {'name': 'System Speakers'}
        outputs = [AudioOutput('System Speakers (USB)', 'endpoint', 'System Speakers (USB) [Loopback]')]
        with patch.dict(sys.modules, {'pyaudiowpatch': mock_pyaudio(pa)}), \
                patch.object(audio_devices, 'list_outputs', return_value=outputs):
            self.assertIsNone(audio_devices.system_default_device())

        pa.terminate.assert_called_once_with()

    def test_preference_keeps_explicit_name_and_resolves_none(self):
        with patch.object(audio_devices, 'system_default_device', return_value='System Speakers') as default:
            self.assertEqual(audio_devices.resolve_preference('Saved Headphones'), 'Saved Headphones')
            default.assert_not_called()
            self.assertEqual(audio_devices.resolve_preference(None), 'System Speakers')
            default.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
