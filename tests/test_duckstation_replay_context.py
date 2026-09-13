import _bootstrap
import struct
import unittest

from duckstation_monitor import stage_context
from duckstation_profiles import PROFILES


class ReplayContextTests(unittest.TestCase):
    def test_replay_suppresses_menu_without_enabling_gameplay_profile(self):
        p = PROFILES[1]
        memory = {p['entry']: p['entry_word'], p['loop']: p['loop_word']}
        class RAM:
            def read(self, address, size):
                return struct.pack('<I', memory[address])
        ram = RAM()
        roots = struct.pack('<II', p['grid'], p['count'])
        self.assertEqual(stage_context(ram, roots, 0), (p, False))
        self.assertEqual(stage_context(ram, roots, 2), (None, True))
        self.assertEqual(stage_context(ram, roots, 1), (None, False))
        self.assertEqual(stage_context(ram, b'\0' * 8, 2), (None, False))
        memory[p['loop']] = 0
        self.assertEqual(stage_context(ram, roots, 2), (None, False))
        self.assertEqual(stage_context(ram, roots, 0), (None, False))


if __name__ == '__main__':
    unittest.main()
