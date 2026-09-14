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

    def _prepare(self, choices, **kwargs):
        with patch.object(launcher_first_run, 'duckstation_directory',
                          return_value=self.portable), \
                patch.object(launcher_first_run, 'choose_file', side_effect=choices) as chooser:
            result = launcher_first_run.prepare(self.root, **kwargs)
        return result, chooser

    def test_explicit_changes_preserve_other_settings_and_cancel_is_noop(self):
        self._prepare([str(self.disc), str(self.bios)])
        settings_path = self.portable / 'settings.ini'
        original_settings = settings_path.read_bytes()
        original_profile = self.profile.read_bytes()
        for change in ('game', 'bios'):
            result, chooser = self._prepare([None], change=change)
            self.assertFalse(result)
            chooser.assert_called_once()
            self.assertEqual(settings_path.read_bytes(), original_settings)
            self.assertEqual(self.profile.read_bytes(), original_profile)

        replacement = self.disc.with_name('replacement.bin')
        replacement.write_bytes(b'disc')
        result, chooser = self._prepare([str(replacement)], change='game')
        self.assertTrue(result)
        chooser.assert_called_once()
        self.assertEqual(settings_path.read_bytes(), original_settings)
        self.assertEqual(json.loads(self.profile.read_text())['game_image'], str(replacement.resolve()))

        replacement_bios = self.bios.with_name('replacement.rom')
        replacement_bios.write_bytes(b'bios')
        profile_before = self.profile.read_bytes()
        result, chooser = self._prepare([str(replacement_bios)], change='bios')
        self.assertTrue(result)
        chooser.assert_called_once_with('Select your PlayStation BIOS', 'BIOS image', '*.bin;*.rom')
        self.assertEqual(self.profile.read_bytes(), profile_before)
        config = launcher_first_run._read_settings(settings_path)
        self.assertEqual(config['BIOS']['PathNTSCU'], replacement_bios.name)
        self.assertEqual(config['Main']['EmulationSpeed'], '1.0')

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
        self.assertEqual(settings['BIOS']['SearchDirectory'], str(self.bios.parent.resolve()))
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
        with patch.object(launcher_first_run.ctypes.windll.user32, 'MessageBoxW') as notice:
            result, chooser = self._prepare([str(self.disc), str(self.bios)])

        self.assertTrue(result)
        notice.assert_not_called()
        self.assertEqual(chooser.call_count, 2)
        chooser.assert_any_call(
            'Select your PaRappa disc image or playlist', 'DuckStation disc image',
            '*.ccd;*.cue;*.bin;*.img;*.iso;*.ecm;*.chd;*.mds;*.pbp;*.m3u')
        settings = configparser.ConfigParser(interpolation=None)
        settings.read(self.portable / 'settings.ini', encoding='utf-8')
        self.assertEqual(settings['Main']['EmulationSpeed'], '1.0')
        self.assertEqual(settings['BIOS']['PathNTSCU'], self.bios.name)
        self.assertEqual(json.loads(self.profile.read_text(encoding='utf-8'))['game_image'],
                         str(self.disc.resolve()))

    def test_all_supported_extensions_accept_an_existing_readable_file(self):
        for suffix in ('.ccd', '.cue', '.bin', '.img', '.iso', '.ecm',
                       '.chd', '.mds', '.pbp', '.m3u'):
            with self.subTest(suffix=suffix):
                disc = self.root / ('dummy-compressed-or-disc' + suffix)
                disc.write_bytes(b'dummy disc content')
                self.assertEqual(launcher_first_run._validate_disc(disc), disc)

    def test_unsupported_archive_and_missing_disc_file_are_rejected(self):
        archive = self.root / 'game.zip'
        archive.write_bytes(b'not a disc')
        with self.assertRaisesRegex(ValueError, 'supported PlayStation disc'):
            launcher_first_run._validate_disc(archive)

        with self.assertRaisesRegex(ValueError, 'existing PlayStation disc'):
            launcher_first_run._validate_disc(self.root / 'missing.chd')

    def test_disc_selection_has_no_format_notice(self):
        with patch.object(launcher_first_run.ctypes.windll.user32, 'MessageBoxW') as notice:
            for suffix in ('.bin', '.img', '.chd'):
                with self.subTest(suffix=suffix):
                    disc = self.root / 'game' / ('game' + suffix)
                    disc.write_bytes(b'dummy disc')
                    with patch.object(launcher_first_run, '_stored_disc', return_value=None):
                        result, _ = self._prepare([str(disc), str(self.bios)])
                    self.assertTrue(result)
            result, chooser = self._prepare([])

        self.assertTrue(result)
        chooser.assert_not_called()
        notice.assert_not_called()

    def test_cue_selection_does_not_show_experimental_notice(self):
        cue = self.root / 'game' / 'game.cue'
        cue.write_text('DuckStation resolves this descriptor.\n', encoding='utf-8')

        with patch.object(launcher_first_run.ctypes.windll.user32, 'MessageBoxW') as notice:
            result, _ = self._prepare([str(cue), str(self.bios)])

        self.assertTrue(result)
        notice.assert_not_called()


if __name__ == '__main__':
    unittest.main()
