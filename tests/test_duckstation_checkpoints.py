"""Pure tests for guarded DuckStation campaign-state saves."""
import _bootstrap
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from duckstation_checkpoints import CampaignCheckpoints, CheckpointSaveError


class FastClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class StateWritingKey:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.calls = []

    def __call__(self, vk_code):
        self.calls.append(vk_code)
        path = self.folder / f"state-{len(self.calls):02d}-{vk_code:02x}.sav"
        with path.open("xb") as stream:
            stream.write(f"hotkey={vk_code:02x}\n".encode("ascii") + b"s" * 2048)
        return True


class CampaignCheckpointsTests(unittest.TestCase):
    def make_manager(self, folder, key, events):
        return CampaignCheckpoints(folder, key, lambda event, **fields:
                                   events.append({"event": event, **fields}))

    def test_maps_every_stage_entry_clear_and_ending_to_expected_function_key(self):
        with tempfile.TemporaryDirectory(prefix="duck_checkpoint_") as temp:
            folder = Path(temp)
            key = StateWritingKey(folder)
            events = []
            manager = self.make_manager(folder, key, events)
            clock = FastClock()
            expected_calls = []
            with patch("duckstation_checkpoints.time.monotonic", clock.monotonic), \
                    patch("duckstation_checkpoints.time.sleep", clock.sleep):
                for stage in range(1, 7):
                    entry = manager.save(stage, "entry", 1000 + stage)
                    clear = manager.save(stage, "clear", 2000 + stage, score=70 + stage)
                    entry_vk = 0x70 + stage - 1
                    clear_vk = 0x7C + stage - 1
                    expected_calls.extend((entry_vk, clear_vk))
                    self.assertEqual(key.calls[-2:], [entry_vk, clear_vk])
                ending = manager.save(6, "ending", 9000, score=91)

            expected_calls.append(0x83)
            self.assertEqual(key.calls, expected_calls)
            self.assertEqual(ending["kind"], "ending")
            self.assertEqual(ending["score"], 91)
            self.assertEqual(len(manager.saved), 13)
            for identity, manifest in manager.saved.items():
                state_path = Path(manifest["path"])
                self.assertEqual(state_path.parent, folder)
                data = state_path.read_bytes()
                self.assertGreater(len(data), 1024)
                self.assertEqual(manifest["size"], len(data))
                self.assertEqual(manifest["sha256"], hashlib.sha256(data).hexdigest())
                manifest_path = folder / f"checkpoint-stage{identity[0]}-{identity[1]}.json"
                self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8")), manifest)
            self.assertEqual(len(list(folder.glob("*.sav"))), 13)

    def test_existing_state_folder_is_rejected_before_any_key(self):
        with tempfile.TemporaryDirectory(prefix="duck_checkpoint_") as temp:
            folder=Path(temp)
            state=folder/'existing.sav';state.write_bytes(b'old state')
            key=StateWritingKey(folder)
            with self.assertRaises(ValueError):self.make_manager(folder,key,[])
            self.assertEqual(key.calls,[])
            self.assertEqual(state.read_bytes(),b'old state')

    def test_duplicate_returns_existing_manifest_without_repeating_key_or_overwriting(self):
        with tempfile.TemporaryDirectory(prefix="duck_checkpoint_") as temp:
            folder = Path(temp)
            key = StateWritingKey(folder)
            events = []
            manager = self.make_manager(folder, key, events)
            clock = FastClock()
            with patch("duckstation_checkpoints.time.monotonic", clock.monotonic), \
                    patch("duckstation_checkpoints.time.sleep", clock.sleep):
                first = manager.save(2, "entry", 1234)
                manifest_path = folder / "checkpoint-stage2-entry.json"
                original_manifest = manifest_path.read_bytes()
                state_path = Path(first["path"])
                original_state = state_path.read_bytes()
                duplicate = manager.save(2, "entry", 5678)

            self.assertEqual(duplicate, first)
            self.assertEqual(key.calls, [0x71])
            self.assertEqual(manifest_path.read_bytes(), original_manifest)
            self.assertEqual(state_path.read_bytes(), original_state)
            self.assertEqual(len(list(folder.glob("*.sav"))), 1)

    def test_timeout_fails_once_and_never_retries_the_hotkey(self):
        with tempfile.TemporaryDirectory(prefix="duck_checkpoint_") as temp:
            key_calls = []
            events = []
            manager = self.make_manager(temp, lambda vk: key_calls.append(vk) or True, events)
            clock = FastClock()
            with patch("duckstation_checkpoints.time.monotonic", clock.monotonic), \
                    patch("duckstation_checkpoints.time.sleep", clock.sleep):
                with self.assertRaises(CheckpointSaveError):
                    manager.save(1, "entry", 100)
                self.assertGreaterEqual(clock.now, 5.0)
                with self.assertRaises(CheckpointSaveError):
                    manager.save(1, "entry", 101)

            self.assertEqual(key_calls, [0x70])
            self.assertEqual([event["event"] for event in events], [
                "checkpoint_save_requested", "checkpoint_save_failed",
            ])
            self.assertEqual(manager.saved, {})
            self.assertEqual(list(Path(temp).glob("*.json")), [])

    def test_rejects_ending_outside_stage_six_without_calling_key(self):
        with tempfile.TemporaryDirectory(prefix="duck_checkpoint_") as temp:
            key = StateWritingKey(temp)
            manager = CampaignCheckpoints(temp, key, lambda *_args, **_kwargs: None)
            with self.assertRaises(ValueError):
                manager.save(5, "ending", 100)
            self.assertEqual(key.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
