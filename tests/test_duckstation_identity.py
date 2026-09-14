import _bootstrap
import hashlib
import unittest
from unittest.mock import Mock, patch

import duckstation_identity as identity


class GameIdentityTests(unittest.TestCase):
    def test_loaded_payload_matches_independently_of_image_filename(self):
        payload = bytes(range(256)) * (identity.LOAD_SIZE // 256)
        expected = hashlib.sha256(payload).hexdigest()
        read = Mock(return_value=payload)
        with patch.object(identity, 'PAYLOAD_SHA256', expected):
            self.assertEqual(identity.verify_loaded_game(read), expected)
        read.assert_called_once_with(identity.LOAD_ADDRESS, identity.LOAD_SIZE)

    def test_changed_or_incomplete_executable_is_rejected(self):
        payload = bytes(range(256)) * (identity.LOAD_SIZE // 256)
        expected = hashlib.sha256(payload).hexdigest()
        for bad in (payload[:-1], b'X' + payload[1:]):
            with self.subTest(size=len(bad)), patch.object(identity, 'PAYLOAD_SHA256', expected):
                with self.assertRaisesRegex(ValueError, 'supported US PaRappa'):
                    identity.verify_loaded_game(Mock(return_value=bad))
