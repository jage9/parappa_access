"""Readiness checks for DuckStation-supported local disc files."""
import _bootstrap
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import launcher_setup
from duckstation_paths import EXECUTABLE_NAME, SETTINGS_NAME


class LauncherSetupDiscTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.portable = self.root / 'tools' / 'duckstation'
        self.portable.mkdir(parents=True)
        (self.portable / EXECUTABLE_NAME).touch()
        (self.portable / SETTINGS_NAME).write_text(
            '[BIOS]\nSearchDirectory = bios\nPathNTSCU = scph5501.bin\n',
            encoding='utf-8')
        bios = self.portable / 'bios' / 'scph5501.bin'
        bios.parent.mkdir()
        bios.touch()
        for button in ('circle', 'x', 'square', 'triangle', 'l1', 'r1'):
            sound = self.root / 'sounds' / (button + '.wav')
            sound.parent.mkdir(parents=True, exist_ok=True)
            sound.touch()
        self.game = self.root / 'game'
        self.game.mkdir()
        self.profile = self.root / 'logs' / 'install-settings.json'
        self.profile.parent.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def _select(self, descriptor):
        self.profile.write_text(json.dumps({'game_image': str(descriptor)}),
                                encoding='utf-8')

    def _check(self):
        with patch.object(launcher_setup, 'duckstation_directory',
                          return_value=self.portable):
            return launcher_setup.check_setup(self.root)

    def test_cue_readiness_only_requires_a_readable_descriptor(self):
        cue = self.game / 'metadata.cue'
        cue.write_text('DuckStation resolves this descriptor and its companions.\n',
                       encoding='utf-8')
        self._select(cue)

        self.assertEqual(self._check(), [])

    def test_ccd_readiness_delegates_companion_loading_to_duckstation(self):
        ccd = self.game / 'PaRappa.ccd'
        ccd.touch()
        self._select(ccd)

        self.assertEqual(self._check(), [])

    def test_missing_supported_disc_file_is_reported(self):
        missing = self.game / 'game.chd'
        self._select(missing)

        expected = str(missing.relative_to(self.root)).replace('/', '\\')
        self.assertEqual(self._check(), ['Missing ' + expected + '.'])


if __name__ == '__main__':
    unittest.main()
