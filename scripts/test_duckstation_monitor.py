import unittest
from duckstation_monitor import completed_scene_reset


class SceneResetTests(unittest.TestCase):
    def test_stage3_entry_does_not_announce_a_final_score(self):
        self.assertFalse(completed_scene_reset(False, 4134, 0, False))

    def test_preroll_and_retry_are_not_completed_rounds(self):
        self.assertFalse(completed_scene_reset(True, 0xFFFFFF70, 0, False))
        self.assertFalse(completed_scene_reset(True, 26153, 0, True))

    def test_observed_round_end_can_announce(self):
        self.assertTrue(completed_scene_reset(True, 26153, 0, False))
