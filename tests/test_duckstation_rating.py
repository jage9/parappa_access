import _bootstrap
import struct
import unittest

from duckstation_rating import rating_name, RatingChanges


def make_state(value, size=0xB0):
    state = bytearray(size)
    struct.pack_into("<h", state, 0x4E, value)
    return state


class RatingNameTests(unittest.TestCase):
    def test_changes_only_and_new_stage_or_retry_baselines(self):
        reader = RatingChanges()
        self.assertIsNone(reader.poll(make_state(1), stage=1, active=True))
        self.assertIsNone(reader.poll(make_state(1), stage=1, active=True))
        self.assertEqual(reader.poll(make_state(2), stage=1, active=True), 'Bad')
        self.assertEqual(reader.poll(make_state(1), stage=1, active=True), 'Good')
        self.assertEqual(reader.poll(make_state(0), stage=1, active=True), 'Cool')
        self.assertIsNone(reader.poll(make_state(1), stage=2, active=True))
        self.assertIsNone(reader.poll(make_state(3), stage=2, active=False))
        self.assertIsNone(reader.poll(make_state(1), stage=2, active=True))
    def test_active_tier_mapping(self):
        self.assertEqual(rating_name(make_state(0), active=True), "Cool")
        self.assertEqual(rating_name(make_state(1), active=True), "Good")
        self.assertEqual(rating_name(make_state(2), active=True), "Bad")
        self.assertEqual(rating_name(make_state(3), active=True), "Awful")

    def test_inactive_snapshot_never_returns_a_stale_tier(self):
        for value in range(4):
            with self.subTest(value=value):
                self.assertIsNone(rating_name(make_state(value)))
                self.assertIsNone(rating_name(make_state(value), active=False))

    def test_unknown_or_truncated_state_is_unavailable(self):
        self.assertIsNone(rating_name(make_state(-1), active=True))
        self.assertIsNone(rating_name(make_state(4), active=True))
        self.assertIsNone(rating_name(bytearray(0x4F), active=True))
        self.assertIsNone(rating_name(None, active=True))


if __name__ == "__main__":
    unittest.main()
