import _bootstrap
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

import duckstation_download as download

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def test_public_file_list_excludes_internal_tools_and_includes_all_sounds(self):
        files = [line for line in (ROOT / 'release-files.txt').read_text().splitlines()
                 if line and not line.startswith('#')]
        self.assertEqual(len(files), len(set(files)))
        for name in files:
            self.assertTrue((ROOT / name).is_file(), name)
            self.assertFalse(name.startswith(('tools/', 'logs/', 'tests/', 'developer/', 'scripts/test', 'scripts/build-')))
            self.assertNotIn(Path(name).suffix, ('.lua', '.ps1'))
        for name in ('circle', 'x', 'square', 'triangle', 'l1', 'r1', 'handoff'):
            self.assertIn('sounds/' + name + '.wav', files)

    def test_unverified_download_never_creates_installation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'input.zip'
            archive.write_bytes(b'not the verified release')
            with self.assertRaises(ValueError):
                download.install_archive(archive, root / 'duckstation')
            self.assertFalse((root / 'duckstation').exists())

    def test_archive_traversal_and_existing_destination_are_rejected(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'input.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('../outside.txt', 'bad')
                zipped.writestr(download.EXECUTABLE_NAME, 'fixture')
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.object(download, 'ARCHIVE_SHA256', digest), self.assertRaises(ValueError):
                download.install_archive(archive, root / 'duckstation')
            self.assertFalse((root / 'outside.txt').exists())
            self.assertFalse((root / 'duckstation').exists())
            (root / 'duckstation').mkdir()
            with self.assertRaises(FileExistsError):
                download.install_archive(archive, root / 'duckstation')
