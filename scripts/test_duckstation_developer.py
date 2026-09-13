"""Pure tests for the opt-in DuckStation developer key driver."""
import unittest

from duckstation_developer import DeveloperController, LANES, Win32WindowBackend, WM_KEYDOWN, WM_KEYUP


class FakeBackend:
    def __init__(self, pid=42, release_results=None):
        self.pid, self.keys = pid, []
        self.release_results = list(release_results or [])
        self.release_calls = 0
    def key(self, vk, down):
        self.keys.append((vk, down))
        if down: return True
        self.release_calls += 1
        return self.release_results.pop(0) if self.release_results else True


class FakeWinAPI:
    def __init__(self):
        self.windows = [11, 22, 33]
        self.pids = {11: 7, 22: 42, 33: 42}
        self.visible_windows = {11, 22}
        self.messages = []
    def enum_windows(self): return self.windows
    def is_window(self, hwnd): return hwnd in self.windows
    def visible(self, hwnd): return hwnd in self.visible_windows
    def window_pid(self, hwnd): return self.pids[hwnd]
    def map_virtual_key(self, vk):
        return {0x49: 0x17, 0x4C: 0x26, 0x4B: 0x25, 0x4A: 0x24,
                0x51: 0x10, 0x45: 0x12, 0x25: 0x4B}.get(vk, 0)
    def post_message(self, hwnd, msg, vk, lparam):
        self.messages.append((hwnd, msg, vk, lparam)); return True


class WindowBackendTests(unittest.TestCase):
    def test_targets_unique_visible_exact_pid_window_with_stock_key_edges(self):
        api = FakeWinAPI()
        backend = Win32WindowBackend(42, api)
        self.assertTrue(backend.key(0x49, True))
        self.assertTrue(backend.key(0x49, False))
        self.assertEqual(api.messages, [
            (22, WM_KEYDOWN, 0x49, 1 | (0x17 << 16)),
            (22, WM_KEYUP, 0x49, 1 | (0x17 << 16) | (3 << 30)),
        ])
        api.pids[22] = 7
        self.assertFalse(backend.key(0x49, True))
        self.assertEqual(len(api.messages), 2)

    def test_stock_duckstation_keys_preserve_each_lane_mask(self):
        self.assertEqual(LANES, {
            1: ("I", 0x49, 0x10), 2: ("L", 0x4C, 0x20),
            3: ("K", 0x4B, 0x40), 4: ("J", 0x4A, 0x80),
            5: ("Q", 0x51, 0x04), 6: ("Q", 0x51, 0x04),
            7: ("E", 0x45, 0x08), 8: ("E", 0x45, 0x08),
        })

    def test_arrow_uses_extended_key_flag_on_both_edges(self):
        api = FakeWinAPI()
        backend = Win32WindowBackend(42, api)
        self.assertTrue(backend.key(0x25, True))
        self.assertTrue(backend.key(0x25, False))
        self.assertEqual(api.messages[0][3], 1 | (0x4B << 16) | (1 << 24))
        self.assertEqual(api.messages[1][3], 1 | (0x4B << 16) | (1 << 24) | (3 << 30))

    def test_targets_unique_visible_exact_pid_window_with_scanencoded_edges(self):
        api = FakeWinAPI()
        backend = Win32WindowBackend(42, api)
        self.assertTrue(backend.key(0x4B, True))
        self.assertTrue(backend.key(0x4B, False))
        self.assertEqual(api.messages, [
            (22, WM_KEYDOWN, 0x4B, 1 | (0x25 << 16)),
            (22, WM_KEYUP, 0x4B, 1 | (0x25 << 16) | (3 << 30)),
        ])
        api.pids[22] = 7
        self.assertFalse(backend.key(0x4B, True))
        self.assertEqual(len(api.messages), 2)

    def test_ambiguous_visible_windows_fail_closed(self):
        api = FakeWinAPI()
        api.visible_windows.add(33)
        with self.assertRaises(RuntimeError):
            Win32WindowBackend(42, api)


class DeveloperControllerTests(unittest.TestCase):
    def make_controller(self, schedule, offset=-6):
        backend = FakeBackend()
        return DeveloperController(42, schedule, offset, backend), backend

    def test_due_key_is_held_until_game_mask_observes_it(self):
        driver, backend = self.make_controller([(100, 3)])
        self.assertEqual(driver.poll(90, 0, True), [])
        self.assertEqual(driver.poll(93, 0, True), [])
        down = driver.poll(94, 0, True)
        self.assertEqual([(e["event"], e.get("key")) for e in down], [("key_down", "K")])
        self.assertEqual(backend.keys, [(0x4B, True)])
        up = driver.poll(95, 0x40, True)
        self.assertEqual(up[0]["reason"], "game_mask_observed")
        self.assertEqual(backend.keys, [(0x4B, True), (0x4B, False)])
        self.assertEqual(driver.close(), [])

    def test_hold_expires_after_six_changed_game_ticks(self):
        driver, backend = self.make_controller([(100, 3)])
        driver.poll(90, 0, True); driver.poll(94, 0, True)
        for tick in range(95, 100): self.assertEqual(driver.poll(tick, 0, True), [])
        expired = driver.poll(100, 0, True)
        self.assertEqual(expired[0]["reason"], "hold_limit")
        self.assertEqual(backend.keys, [(0x4B, True), (0x4B, False)])

    def test_invalid_context_releases_and_latches_off(self):
        driver, backend = self.make_controller([(100, 3)])
        driver.poll(90, 0, True); driver.poll(94, 0, True)
        events = driver.poll(95, 0, False)
        self.assertEqual(events[0]["event"], "key_up")
        self.assertEqual(events[-1]["reason"], "invalid_context")
        self.assertEqual(driver.poll(96, 0, True), [])
        self.assertEqual(backend.keys, [(0x4B, True), (0x4B, False)])

    def test_tick_reset_releases_and_requires_new_driver(self):
        driver, backend = self.make_controller([(100, 3)])
        driver.poll(90, 0, True); driver.poll(94, 0, True)
        events = driver.poll(93, 0, True)
        self.assertEqual(events[0]["event"], "key_up")
        self.assertEqual(events[-1]["reason"], "tick_reset")
        self.assertEqual(driver.poll(94, 0, True), [])
        self.assertEqual(backend.keys, [(0x4B, True), (0x4B, False)])

    def test_stale_or_multiple_due_events_are_skipped_without_catchup(self):
        driver, backend = self.make_controller([(100, 3), (101, 2)])
        driver.poll(90, 0, True)
        skipped = driver.poll(95, 0, True)
        self.assertEqual([e["reason"] for e in skipped], ["multiple_due", "multiple_due"])
        self.assertEqual(backend.keys, [])

    def test_large_poll_gap_skips_single_due_event(self):
        driver, backend = self.make_controller([(100, 3)])
        driver.poll(90, 0, True)
        skipped = driver.poll(101, 0, True)
        self.assertEqual(skipped[0]["reason"], "poll_gap")
        self.assertEqual(backend.keys, [])

    def test_forward_tick_gap_releases_active_key_disables_and_skips_due_schedule(self):
        backend = FakeBackend()
        driver = DeveloperController(42, [(100, 3), (110, 2)], -6, backend)
        driver.poll(90, 0, True)
        driver.poll(94, 0, True)
        events = driver.poll(105, 0, True)
        self.assertEqual(events[0]["event"], "key_up")
        self.assertEqual(events[0]["reason"], "tick_gap")
        self.assertTrue(events[0]["posted"])
        self.assertTrue(any(e["event"] == "driver_disabled" and e["reason"] == "tick_gap"
                            for e in events))
        self.assertTrue(any(e["event"] == "stale_event_skipped" and e["reason"] == "poll_gap"
                            for e in events))
        self.assertEqual(backend.keys, [(0x4B, True), (0x4B, False)])
        self.assertEqual(driver.poll(106, 0, True), [])

    def test_close_retries_failed_keyup_reports_failure_and_can_retry_after_close(self):
        backend = FakeBackend(release_results=[False, False, False, True])
        driver = DeveloperController(42, [(100, 3)], -6, backend)
        driver.poll(90, 0, True)
        driver.poll(94, 0, True)

        failed = driver.close()
        self.assertEqual(failed[0]["event"], "key_up")
        self.assertFalse(failed[0]["posted"])
        self.assertEqual(failed[0]["attempts"], 3)
        self.assertEqual(failed[-1]["event"], "key_release_failed")
        self.assertIsNotNone(driver.active)

        retried = driver.close()
        self.assertEqual(retried[0]["event"], "key_up")
        self.assertTrue(retried[0]["posted"])
        self.assertEqual(retried[0]["attempts"], 1)
        self.assertIsNone(driver.active)
        self.assertEqual(backend.release_calls, 4)


if __name__ == "__main__": unittest.main(verbosity=2)
