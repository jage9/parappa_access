import _bootstrap
import configparser
from pathlib import Path
import tempfile
import unittest
from duckstation_cards import configure_test_cards, configure_player_cards


class CardConfigurationTests(unittest.TestCase):
    def test_nonpersistent_card_removes_old_paths_and_preserves_other_settings(self):
        settings = configparser.ConfigParser(interpolation=None)
        settings.optionxform = str
        settings.read_dict({
            'MemoryCards': {
                'Card1Type': 'Shared',
                'Card1Path': 'old-slot-1.mcd',
                'Card2Type': 'PerGameTitle',
                'Card2Path': 'old-slot-2.mcd',
                'UsePlaylistTitle': 'true',
            },
            'Audio': {'OutputDevice': 'Existing endpoint'},
        })

        configure_test_cards(settings, nonpersistent=True)

        self.assertEqual(settings.get('MemoryCards', 'Card1Type'), 'NonPersistent')
        self.assertEqual(settings.get('MemoryCards', 'Card2Type'), 'None')
        self.assertFalse(settings.has_option('MemoryCards', 'Card1Path'))
        self.assertFalse(settings.has_option('MemoryCards', 'Card2Path'))
        self.assertEqual(settings.get('MemoryCards', 'UsePlaylistTitle'), 'true')
        self.assertEqual(settings.get('Audio', 'OutputDevice'), 'Existing endpoint')

    def test_default_disables_both_slots_and_creates_memory_cards_section(self):
        settings = configparser.ConfigParser(interpolation=None)
        settings.optionxform = str
        settings.read_dict({'Audio': {'OutputDevice': 'Existing endpoint'}})

        configure_test_cards(settings)

        self.assertTrue(settings.has_section('MemoryCards'))
        self.assertEqual(settings.get('MemoryCards', 'Card1Type'), 'None')
        self.assertEqual(settings.get('MemoryCards', 'Card2Type'), 'None')
        self.assertFalse(settings.has_option('MemoryCards', 'Card1Path'))
        self.assertFalse(settings.has_option('MemoryCards', 'Card2Path'))
        self.assertEqual(settings.get('Audio', 'OutputDevice'), 'Existing endpoint')

    def test_nonpersistent_flag_must_be_exactly_bool(self):
        settings = configparser.ConfigParser(interpolation=None)
        invalid_values = (0, 1, None, 'true')

        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    configure_test_cards(settings, nonpersistent=value)
                self.assertFalse(settings.has_section('MemoryCards'))


class PlayerCardTests(unittest.TestCase):
    def test_uses_existing_import_without_changing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / 'tools/duckstation/memcards/redux-import-slot1.mcd'
            existing.parent.mkdir(parents=True)
            (existing.parent.parent / 'settings.ini').touch()
            existing.write_bytes(b'MC' + bytes(131070))
            before = existing.read_bytes()
            settings = configparser.ConfigParser()
            configure_player_cards(root, settings)
            self.assertEqual(settings.get('MemoryCards', 'Card1Path'), str(existing.resolve()))
            self.assertEqual(existing.read_bytes(), before)
            self.assertFalse((root / 'tools/pcsx-redux').exists())

    def test_new_install_only_configures_paths_and_preserves_custom_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = configparser.ConfigParser()
            settings.read_dict({'MemoryCards': {'Card2Type': 'Shared', 'Card2Path': 'mine.mcd'}})
            configure_player_cards(root, settings)
            self.assertEqual(settings.get('MemoryCards', 'Card1Type'), 'Shared')
            self.assertEqual(settings.get('MemoryCards', 'Card2Path'), 'mine.mcd')
            self.assertEqual(list(root.iterdir()), [])
