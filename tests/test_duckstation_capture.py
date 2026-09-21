"""Pure bounded-duration tests for DuckStation playback capture."""
import _bootstrap
import tempfile
import json
import unittest
from pathlib import Path

from duckstation_capture import (
    DEFAULT_AUDIO_SECONDS,
    HELPER_KEY_MAP,
    KEY_MAP,
    MAX_AUDIO_SECONDS,
    READY_MARKER,
    ROOT,
    DuckStationCapture,
    NullCapture,
    filter_key_event,
)
from duckstation_keyboard import HINT_VK, LYRICS_VK, RATING_VK, SCORE_VK, SUBTITLES_VK


class ReadyRecorder:
    def __init__(self, log):
        self.returncode = None
        log.write(READY_MARKER + "\n")
        log.flush()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = 0


class DuckStationCaptureDurationTests(unittest.TestCase):
    def setUp(self):
        self.logs_root = ROOT / "logs"
        self.logs_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_capture_", dir=self.logs_root)
        self.session_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_capture(self, **kwargs):
        return DuckStationCapture(
            self.session_dir,
            123,
            "test loopback",
            hook_enabled=False,
            **kwargs,
        )

    def test_default_remains_180_seconds(self):
        commands = []

        def popen_factory(command, **kwargs):
            commands.append(command)
            return ReadyRecorder(kwargs["stdout"])

        capture = self.make_capture(popen_factory=popen_factory)
        self.assertEqual(DEFAULT_AUDIO_SECONDS, 180)
        self.assertEqual(capture.audio_seconds, 180)
        self.assertEqual(capture._manifest()["playback_capture"]["max_seconds"], 180)
        try:
            capture._start_recorder()
            command = commands[0]
            seconds_index = command.index("--seconds") + 1
            self.assertEqual(command[seconds_index], "180")
        finally:
            capture._stop_recorder()

    def test_900_seconds_is_passed_to_recorder_and_manifest(self):
        commands = []

        def popen_factory(command, **kwargs):
            commands.append(command)
            return ReadyRecorder(kwargs["stdout"])

        capture = self.make_capture(audio_seconds=900, popen_factory=popen_factory)
        try:
            capture._start_recorder()
            command = commands[0]
            seconds_index = command.index("--seconds") + 1
            self.assertEqual(command[seconds_index], "900")
            self.assertEqual(capture._manifest()["playback_capture"]["max_seconds"], 900)
        finally:
            capture._stop_recorder()

    def test_duration_must_be_finite_positive_number_at_most_900(self):
        self.assertEqual(MAX_AUDIO_SECONDS, 900)
        invalid_values = (0, -1, 900.01, float("nan"), float("inf"), 1 << 4096, True, "900")
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.make_capture(audio_seconds=value)


class DuckStationCaptureKeyboardTests(unittest.TestCase):
    def make_event(self, vk_code):
        return filter_key_event(
            vk_code,
            "down",
            armed=True,
            foreground_pid=123,
            target_pid=123,
            perf_counter_ns=456,
            windows_event_time_ms=789,
        )

    def test_stock_duckstation_keys_map_to_buttons(self):
        self.assertEqual(KEY_MAP, {
            0x49: ("I", "Triangle"),
            0x4C: ("L", "Circle"),
            0x4B: ("K", "Cross"),
            0x4A: ("J", "Square"),
            0x51: ("Q", "L1"),
            0x45: ("E", "R1"),
        })
        for vk_code, (key, button) in KEY_MAP.items():
            with self.subTest(key=key):
                event = self.make_event(vk_code)
                self.assertEqual(event["event"], "keyboard")
                self.assertEqual((event["key"], event["button"]), (key, button))
                self.assertEqual(event["vk_code"], vk_code)

    def test_score_rating_and_hint_keys_are_logged_as_helpers(self):
        self.assertEqual(HELPER_KEY_MAP, {
            SCORE_VK: ("Z", "score"),
            RATING_VK: ("X", "rating"),
            HINT_VK: ("Slash", "hint"),
            LYRICS_VK: ("Y", "lyrics"),
            SUBTITLES_VK: ("U", "subtitles"),
        })
        for vk_code, (key, helper) in HELPER_KEY_MAP.items():
            with self.subTest(helper=helper):
                event = self.make_event(vk_code)
                self.assertEqual(event["event"], "keyboard_helper")
                self.assertEqual((event["key"], event["helper"]), (key, helper))
                self.assertNotIn("button", event)

    def test_helper_keys_use_the_same_focus_and_modifier_gates(self):
        self.assertIsNone(filter_key_event(
            SCORE_VK, "down", armed=False, foreground_pid=123, target_pid=123,
            perf_counter_ns=456, windows_event_time_ms=789,
        ))
        self.assertIsNone(filter_key_event(
            HINT_VK, "down", armed=True, foreground_pid=123, target_pid=123,
            ctrl_down=True, perf_counter_ns=456, windows_event_time_ms=789,
        ))


class PublicDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.logs_root = ROOT / "logs"
        self.logs_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_public_capture_", dir=self.logs_root)
        self.session_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_text_diagnostics_do_not_spawn_audio_or_emit_raw_memory_fields(self):
        capture = DuckStationCapture(
            self.session_dir, 123, hook_enabled=False, record_audio=False,
            public_diagnostics=True,
        )
        capture.start()
        try:
            self.assertFalse(capture.record_event("menu_registers", registers_hex="deadbeef"))
            self.assertTrue(capture.record_event(
                "cue_submission", button="TRIANGLE", tick=112, register_hex="deadbeef",
                before_ns=10, after_ns=20, result=True, status="submitted",
            ))
        finally:
            capture.stop()

        self.assertEqual({path.name for path in self.session_dir.iterdir()}, {"manifest.json", "events.jsonl"})
        manifest = json.loads((self.session_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["playback_capture"]["enabled"])
        self.assertNotIn("session_directory", manifest)
        self.assertNotIn("loopback_name", manifest)
        events = [json.loads(line) for line in (self.session_dir / "events.jsonl").read_text().splitlines()]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "cue_submission")
        self.assertNotIn("register_hex", events[0])

    def test_public_diagnostics_cannot_be_configured_to_record_audio(self):
        with self.assertRaises(ValueError):
            DuckStationCapture(
                self.session_dir, 123, public_diagnostics=True, record_audio=True,
            )

    def test_null_capture_never_creates_a_session_or_accepts_events(self):
        capture = NullCapture(123)
        self.assertIsNone(capture.session_dir)
        self.assertFalse(capture.enabled)
        self.assertIs(capture.start(), capture)
        capture.set_armed(True)
        self.assertFalse(capture.record_event("score_requested", score=18))
        capture.stop()


if __name__ == "__main__":
    unittest.main()
