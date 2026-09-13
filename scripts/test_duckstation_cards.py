import configparser
import json
from pathlib import Path
import tempfile
import unittest
from duckstation_cards import configure_test_cards, import_redux_cards


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


class CardImportTests(unittest.TestCase):
    def test_copy_preserves_original_and_existing_duck_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'tools' / 'pcsx-redux'
            source.mkdir(parents=True)
            original = b'MC' + bytes(131070)
            (source / 'card.mcd').write_bytes(original)
            (source / 'pcsx.json').write_text(json.dumps({'emulator': {
                'Mcd1': 'card.mcd', 'Mcd1Inserted': True, 'Mcd2Inserted': False}}))
            target = import_redux_cards(root)[1]
            self.assertEqual(target.read_bytes(), original)
            progress = b'MC' + b'X' + bytes(131069)
            target.write_bytes(progress)
            self.assertEqual(import_redux_cards(root)[1].read_bytes(), progress)
            self.assertEqual((source / 'card.mcd').read_bytes(), original)

    def test_invalid_card_is_not_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'tools' / 'pcsx-redux'
            source.mkdir(parents=True)
            (source / 'card.mcd').write_bytes(b'bad')
            (source / 'pcsx.json').write_text(json.dumps({'emulator': {'Mcd1': 'card.mcd'}}))
            with self.assertRaises(ValueError):
                import_redux_cards(root)
            self.assertFalse((root / 'tools' / 'research').exists())
