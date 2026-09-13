"""Regression tests for reusing first-run choices and repairing a missing BIOS."""
import _bootstrap
import configparser
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import launcher_first_run
from duckstation_paths import EXECUTABLE_NAME
from duckstation_profiles import DISC_IMG_SHA256


class _ExpectedDiscHash:
    def hexdigest(self):
        return DISC_IMG_SHA256


class LauncherFirstRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.portable = self.root / 'tools' / 'duckstation'
        self.portable.mkdir(parents=True)
        (self.portable / EXECUTABLE_NAME).touch()
        self.disc = self.root / 'game' / 'PaRappa.ccd'
        self.disc.parent.mkdir()
        self.disc.write_bytes(b'ccd')
        self.disc.with_suffix('.img').write_bytes(b'img')
        self.disc.with_suffix('.sub').write_bytes(b'sub')
        self.bios = self.root / 'user-bios' / 'scph5501.bin'
        self.bios.parent.mkdir()
        self.bios.write_bytes(b'bios')
        self.profile = self.root / 'logs' / 'install-settings.json'

    def tearDown(self):
        self.temp.cleanup()

    def _store_disc(self, path=None):
        self.profile.parent.mkdir(parents=True, exist_ok=True)
        self.profile.write_text(json.dumps({'game_image': str(path or self.disc)}),
                                encoding='utf-8')

    def _prepare(self, choices):
        with patch.object(launcher_first_run, 'duckstation_directory',
                          return_value=self.portable), \
                patch.object(launcher_first_run, 'choose_file', side_effect=choices) as chooser, \
                patch.object(launcher_first_run.hashlib, 'file_digest',
                             return_value=_ExpectedDiscHash()):
            result = launcher_first_run.prepare(self.root)
        return result, chooser

    def test_valid_stored_disc_and_bios_skip_both_file_dialogs(self):
        self._store_disc()
        self.bios.parent.mkdir(exist_ok=True)
        settings_text = (
            '[Main]\nEmulationSpeed = 0.75\n'
            '[BIOS]\nSearchDirectory = ' + str(self.bios.parent) +
            '\nPathNTSCU = ' + self.bios.name + '\nPatchFastBoot = true\n'
            '[Custom]\nKeepThis = yes\n'
        )
        settings_path = self.portable / 'settings.ini'
        settings_path.write_text(settings_text, encoding='utf-8')

        result, chooser = self._prepare([])

        self.assertTrue(result)
        chooser.assert_not_called()
        self.assertEqual(settings_path.read_text(encoding='utf-8'), settings_text)

    def test_missing_bios_is_reselected_without_losing_other_settings(self):
        self._store_disc()
        settings_path = self.portable / 'settings.ini'
        settings_path.write_text(
            '[Main]\nEmulationSpeed = 0.75\n'
            '[Audio]\nBackend = WASAPI\nBufferMS = 11\n'
            '[Custom]\nKeepThis = yes\n', encoding='utf-8')

        result, chooser = self._prepare([str(self.bios)])

        self.assertTrue(result)
        chooser.assert_called_once_with('Select your PlayStation BIOS', 'BIOS image', '*.bin;*.rom')
        settings = configparser.ConfigParser(interpolation=None)
        settings.read(settings_path, encoding='utf-8')
        self.assertEqual(settings['Main']['EmulationSpeed'], '0.75')
        self.assertEqual(settings['Audio']['Backend'], 'WASAPI')
        self.assertEqual(settings['Audio']['BufferMS'], '11')
        self.assertEqual(settings['Custom']['KeepThis'], 'yes')
        self.assertEqual(settings['BIOS']['SearchDirectory'], str(self.bios.parent))
        self.assertEqual(settings['BIOS']['PathNTSCU'], self.bios.name)

    def test_invalid_configured_bios_is_reselected(self):
        self._store_disc()
        settings_path = self.portable / 'settings.ini'
        settings_path.write_text(
            '[Main]\nUnrelated = retained\n'
            '[BIOS]\nSearchDirectory = ' + str(self.root / 'missing') +
            '\nPathNTSCU = nonexistent.bin\n', encoding='utf-8')

        result, chooser = self._prepare([str(self.bios)])

        self.assertTrue(result)
        chooser.assert_called_once()
        settings = configparser.ConfigParser(interpolation=None)
        settings.read(settings_path, encoding='utf-8')
        self.assertEqual(settings['Main']['Unrelated'], 'retained')
        self.assertEqual(settings['BIOS']['PathNTSCU'], self.bios.name)

    def test_initial_setup_still_selects_disc_and_bios_and_writes_defaults(self):
        result, chooser = self._prepare([str(self.disc), str(self.bios)])

        self.assertTrue(result)
        self.assertEqual(chooser.call_count, 2)
        settings = configparser.ConfigParser(interpolation=None)
        settings.read(self.portable / 'settings.ini', encoding='utf-8')
        self.assertEqual(settings['Main']['EmulationSpeed'], '1.0')
        self.assertEqual(settings['BIOS']['PathNTSCU'], self.bios.name)
        self.assertEqual(json.loads(self.profile.read_text(encoding='utf-8'))['game_image'],
                         str(self.disc.resolve()))


if __name__ == '__main__':
    unittest.main()
