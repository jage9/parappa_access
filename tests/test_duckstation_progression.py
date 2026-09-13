"""Tests for the opt-in stage-aware DuckStation key driver."""
import _bootstrap
import unittest

from duckstation_progression import MultiStageDeveloper, SCHEDULE_METADATA


def schedules(first_events=None):
    first_events = first_events or {}
    result = {}
    for stage, count in SCHEDULE_METADATA["event_counts"].items():
        first = first_events.get(stage, (120, 1))
        result[stage] = [first]
        result[stage].extend((24000 + 24 * index, 1) for index in range(count - 1))
    return result


class FakeBackend:
    def __init__(self, pid):
        self.pid = pid
        self.keys = []

    def key(self, vk, down):
        self.keys.append((vk, down))
        return True


class MultiStageDeveloperTests(unittest.TestCase):
    def test_schedule_metadata_covers_all_stages_and_source_rows(self):
        self.assertEqual(set(SCHEDULE_METADATA["event_counts"]), set(range(1, 7)))
        self.assertEqual(sum(SCHEDULE_METADATA["event_counts"].values()), 667)
        self.assertEqual(SCHEDULE_METADATA["source_files"][1], "logs/timing-stage1-seed.lua")
        self.assertEqual(SCHEDULE_METADATA["source_files"][6], "logs/passive-stage-seeds.lua")

    def test_requires_complete_valid_noncolliding_stage_schedules(self):
        missing = schedules()
        del missing[6]
        with self.assertRaises(ValueError):
            MultiStageDeveloper(42, missing)

        invalid = schedules()
        invalid[4][1] = (invalid[4][0][0], 2)
        with self.assertRaises(ValueError):
            MultiStageDeveloper(42, invalid)

        invalid = schedules()
        invalid[3] = [(True, 1)]
        with self.assertRaises(ValueError):
            MultiStageDeveloper(42, invalid)

        invalid = schedules()
        invalid[2] = [(100, 9)]
        invalid[2].extend((24000 + 24 * index, 1) for index in range(87))
        with self.assertRaises(ValueError):
            MultiStageDeveloper(42, invalid)

        invalid = schedules()
        invalid[5][0] = (121, 1)
        with self.assertRaises(ValueError):
            MultiStageDeveloper(42, invalid)

    def test_round_routes_scheduled_key_and_releases_on_game_mask(self):
        backends = []

        def backend_factory(pid):
            backend = FakeBackend(pid)
            backends.append(backend)
            return backend

        driver = MultiStageDeveloper(42, schedules(), backend_factory=backend_factory)
        self.assertEqual(driver.poll(1, 108, 0, True), [])  # establish baseline
        events = driver.poll(1, 114, 0, True)
        self.assertEqual([(event["event"], event["stage"]) for event in events], [("key_down", 1)])
        self.assertEqual(events[0]["key"], "I")

        events = driver.poll(1, 115, 0x10, True)
        self.assertEqual([(event["event"], event["stage"]) for event in events], [("key_up", 1)])
        self.assertEqual(events[0]["reason"], "game_mask_observed")
        self.assertEqual(backends[0].keys, [(0x49, True), (0x49, False)])
        self.assertEqual(driver.close(), [])

    def test_false_active_gate_closes_round_and_next_round_restarts(self):
        backends = []

        def backend_factory(pid):
            backend = FakeBackend(pid)
            backends.append(backend)
            return backend

        driver = MultiStageDeveloper(42, schedules({2: (120, 2)}), backend_factory=backend_factory)
        self.assertEqual(driver.poll(2, 108, 0, False), [])
        self.assertEqual(driver.poll(2, 108, 0, True), [])
        down = driver.poll(2, 114, 0, True)
        self.assertEqual(down[0]["event"], "key_down")
        released = driver.poll(2, 115, 0, False)
        self.assertEqual(released[0]["event"], "key_up")
        self.assertEqual(released[0]["stage"], 2)

        self.assertEqual(driver.poll(2, 108, 0, True), [])
        down = driver.poll(2, 114, 0, True)
        self.assertEqual(down[0]["event"], "key_down")
        self.assertEqual(len(backends), 2)
        self.assertEqual(backends[0].keys, [(0x4C, True), (0x4C, False)])
        driver.close()

    def test_stage_change_releases_old_key_and_uses_new_stage_schedule(self):
        backends = []

        def backend_factory(pid):
            backend = FakeBackend(pid)
            backends.append(backend)
            return backend

        stage_schedules = schedules({2: (144, 2)})
        driver = MultiStageDeveloper(42, stage_schedules, backend_factory=backend_factory)
        driver.poll(1, 108, 0, True)
        self.assertEqual(driver.poll(1, 114, 0, True)[0]["event"], "key_down")

        events = driver.poll(2, 108, 0, True)
        self.assertEqual([(event["event"], event["stage"]) for event in events], [("key_up", 1)])
        driver.poll(2, 114, 0, True)
        driver.poll(2, 120, 0, True)
        driver.poll(2, 126, 0, True)
        driver.poll(2, 132, 0, True)
        self.assertEqual(driver.poll(2, 138, 0, True)[0]["key"], "L")
        self.assertEqual(backends[0].keys, [(0x49, True), (0x49, False)])
        self.assertEqual(backends[1].keys, [(0x4C, True)])
        driver.close()

    def test_fail_closed_driver_is_not_restarted_until_round_boundary(self):
        backends = []

        def backend_factory(pid):
            backend = FakeBackend(pid)
            backends.append(backend)
            return backend

        stage_schedules = schedules()
        driver = MultiStageDeveloper(42, stage_schedules, backend_factory=backend_factory)
        driver.poll(1, 108, 0, True)
        driver.poll(1, 114, 0, True)
        failed = driver.poll(1, 121, 0, True)
        self.assertIn("driver_disabled", [event["event"] for event in failed])
        self.assertEqual(driver.poll(1, 122, 0, True), [])
        self.assertEqual(len(backends), 1)

        driver.poll(1, 0, 0, False)
        self.assertEqual(driver.poll(1, 0, 0, True), [])
        self.assertEqual(len(backends), 2)
        driver.close()

    def test_close_releases_once_and_makes_future_polls_inert(self):
        backend = FakeBackend(42)
        driver = MultiStageDeveloper(42, schedules(), backend_factory=lambda _pid: backend)
        driver.poll(1, 108, 0, True)
        driver.poll(1, 114, 0, True)
        closed = driver.close()
        self.assertEqual([(event["event"], event["stage"]) for event in closed], [("key_up", 1)])
        self.assertEqual(driver.close(), [])
        self.assertEqual(driver.poll(1, 115, 0, True), [])
        self.assertEqual(backend.keys, [(0x49, True), (0x49, False)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
