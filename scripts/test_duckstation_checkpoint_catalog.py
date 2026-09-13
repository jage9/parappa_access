"""Read-only tests for DuckStation campaign checkpoint discovery."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from duckstation_checkpoint_catalog import list_checkpoints, load_checkpoint


class CheckpointCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / "logs" / "duck-checkpoints" / "session-1"
        self.folder.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def create_checkpoint(self, stage=2, kind="entry", content=b"saved state bytes"):
        save_path = self.folder / f"stage{stage}-{kind}.sav"
        save_path.write_bytes(content)
        manifest_path = self.folder / f"checkpoint-stage{stage}-{kind}.json"
        manifest = {
            "path": str(save_path.resolve()),
            "stage": stage,
            "kind": kind,
            "tick": 234,
            "score": 12500,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path, save_path, manifest

    def write_manifest(self, path, manifest):
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_load_checkpoint_validates_and_returns_absolute_paths_without_writing(self):
        manifest_path, save_path, manifest = self.create_checkpoint()
        before_manifest = manifest_path.read_bytes()
        before_save = save_path.read_bytes()

        checkpoint = load_checkpoint(manifest_path.relative_to(self.root), self.root)

        self.assertEqual(checkpoint["stage"], 2)
        self.assertEqual(checkpoint["kind"], "entry")
        self.assertEqual(checkpoint["path"], str(save_path.resolve()))
        self.assertEqual(checkpoint["manifest_path"], str(manifest_path.resolve()))
        self.assertEqual(checkpoint["sha256"], manifest["sha256"])
        self.assertEqual(manifest_path.read_bytes(), before_manifest)
        self.assertEqual(save_path.read_bytes(), before_save)

    def test_load_rejects_bad_stage_kind_filename_and_ending_stage(self):
        cases = [
            (True, "entry", "stage must"),
            (7, "entry", "stage must"),
            (2, "practice", "kind must"),
            (5, "ending", "only valid for stage 6"),
        ]
        for stage, kind, message in cases:
            with self.subTest(stage=stage, kind=kind):
                manifest_path, _, manifest = self.create_checkpoint()
                manifest["stage"], manifest["kind"] = stage, kind
                self.write_manifest(manifest_path, manifest)
                with self.assertRaisesRegex(ValueError, message):
                    load_checkpoint(manifest_path, self.root)

        manifest_path, _, manifest = self.create_checkpoint()
        manifest["stage"] = 3
        self.write_manifest(manifest_path, manifest)
        with self.assertRaisesRegex(ValueError, "filename does not match"):
            load_checkpoint(manifest_path, self.root)

    def test_load_rejects_missing_wrong_extension_and_outside_save_files(self):
        manifest_path, save_path, manifest = self.create_checkpoint()
        outside = self.root / "outside.sav"
        outside.write_bytes(b"outside")

        for value, message in [
            (str(self.folder / "missing.sav"), "unavailable"),
            (str(save_path.with_suffix(".bin")), "unavailable"),
            (str(outside), "inside its manifest session"),
        ]:
            with self.subTest(path=value):
                manifest["path"] = value
                self.write_manifest(manifest_path, manifest)
                with self.assertRaisesRegex(ValueError, message):
                    load_checkpoint(manifest_path, self.root)

    def test_load_rejects_size_or_sha256_mismatch(self):
        manifest_path, save_path, manifest = self.create_checkpoint()
        save_path.write_bytes(b"changed save state")
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            load_checkpoint(manifest_path, self.root)

        manifest["size"] = save_path.stat().st_size
        self.write_manifest(manifest_path, manifest)
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            load_checkpoint(manifest_path, self.root)

    def test_list_only_discovers_valid_named_manifests_and_records_invalid_ones(self):
        self.create_checkpoint(3, "clear")
        self.create_checkpoint(1, "entry")
        invalid_path, _, invalid = self.create_checkpoint(2, "entry")
        invalid["sha256"] = "0" * 64
        self.write_manifest(invalid_path, invalid)
        invalid_stage, _, _ = self.create_checkpoint(7, "entry")

        (self.folder / "provenance.json").write_text("{}", encoding="utf-8")
        (self.folder / "events.json").write_text("{}", encoding="utf-8")
        nested = self.folder / "nested"
        nested.mkdir()
        (nested / "checkpoint-stage4-entry.json").write_text("{}", encoding="utf-8")

        errors = []
        checkpoints = list_checkpoints(self.root, errors=errors)

        self.assertEqual([(item["stage"], item["kind"]) for item in checkpoints],
                         [(1, "entry"), (3, "clear")])
        self.assertTrue(all(Path(item["manifest_path"]).is_absolute() for item in checkpoints))
        self.assertEqual(len(errors), 2)
        by_path = {item["path"]: item["error"] for item in errors}
        self.assertIn("SHA-256 mismatch", by_path[str(invalid_path.resolve())])
        self.assertIn("stage must", by_path[str(invalid_stage.resolve())])

    def test_load_rejects_manifests_outside_new_checkpoint_root(self):
        outside = self.root / "logs" / "duck-sessions" / "provenance.json"
        outside.parent.mkdir(parents=True)
        outside.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must be under"):
            load_checkpoint(outside, self.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
