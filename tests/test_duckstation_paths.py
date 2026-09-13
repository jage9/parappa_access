"""Tests for the simple and legacy DuckStation install locations."""
import _bootstrap
from pathlib import Path
import tempfile
import unittest

from duckstation_paths import (
    EXECUTABLE_NAME,
    SETTINGS_NAME,
    duckstation_directory,
)


class DuckStationPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.simple = self.root / "tools" / "duckstation"
        self.legacy = (self.root / "tools" / "research" / "duckstation-stock"
                       / "portable")

    def tearDown(self):
        self.temp.cleanup()

    def test_new_install_defaults_to_simple_location(self):
        self.assertEqual(duckstation_directory(self.root), self.simple)

    def test_simple_location_wins_when_it_has_the_executable(self):
        self.simple.mkdir(parents=True)
        (self.simple / EXECUTABLE_NAME).touch()
        self.legacy.mkdir(parents=True)

        self.assertEqual(duckstation_directory(self.root), self.simple)

    def test_simple_location_wins_when_it_only_has_settings(self):
        self.simple.mkdir(parents=True)
        (self.simple / SETTINGS_NAME).touch()
        self.legacy.mkdir(parents=True)

        self.assertEqual(duckstation_directory(self.root), self.simple)

    def test_existing_legacy_location_remains_supported(self):
        self.legacy.mkdir(parents=True)

        self.assertEqual(duckstation_directory(self.root), self.legacy)

    def test_empty_simple_folder_does_not_shadow_existing_legacy_install(self):
        self.simple.mkdir(parents=True)
        self.legacy.mkdir(parents=True)

        self.assertEqual(duckstation_directory(self.root), self.legacy)


if __name__ == "__main__":
    unittest.main()
