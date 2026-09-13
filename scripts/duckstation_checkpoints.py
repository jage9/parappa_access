"""Save guarded DuckStation campaign checkpoints through its state hotkeys."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time


ENTRY_VK_BASE = 0x70  # F1..F6: SaveGlobalState1..6.
CLEAR_VK_BASE = 0x7C  # F13..F18: SaveGameState1..6.
ENDING_VK = 0x83  # F20: SaveGameState7.
SAVE_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.025
STABLE_SECONDS = 0.15
MIN_STABLE_SIZE = 1024


class CheckpointSaveError(RuntimeError):
    """Raised when a checkpoint hotkey does not produce one stable state."""


class CampaignCheckpoints:
    """Save each stage entry/clear and the ending once into a fresh folder.

    ``key`` receives one Windows virtual-key code. ``record`` follows the
    capture ``record_event(event_name, **fields)`` interface. State files are
    only observed and hashed; this class never renames or edits them.
    """

    def __init__(self, folder, key, record):
        self.folder = Path(folder).resolve()
        if not self.folder.is_dir():
            raise ValueError(f"Checkpoint folder must already exist: {self.folder}")
        if any(self.folder.glob('*.sav')):
            raise ValueError('Checkpoint saving requires a fresh folder without existing save states')
        if not callable(key) or not callable(record):
            raise TypeError("key and record must be callable")
        self.key = key
        self.record = record
        self.saved: dict[tuple[int, str], dict] = {}
        self._attempted: set[tuple[int, str]] = set()

    @staticmethod
    def _identity(stage, kind):
        if isinstance(stage, bool) or not isinstance(stage, int) or not 1 <= stage <= 6:
            raise ValueError("stage must be an integer from 1 through 6")
        if kind not in ("entry", "clear", "ending"):
            raise ValueError("kind must be 'entry', 'clear', or 'ending'")
        if kind == "ending" and stage != 6:
            raise ValueError("ending is only valid for stage 6")
        if kind != "ending" and isinstance(stage, int) and not 1 <= stage <= 6:
            raise ValueError("stage checkpoints are only valid for stages 1 through 6")
        return stage, kind

    @staticmethod
    def _hotkey(stage, kind):
        if kind == "entry":
            return ENTRY_VK_BASE + stage - 1
        if kind == "clear":
            return CLEAR_VK_BASE + stage - 1
        return ENDING_VK

    def _new_states(self, existing_names):
        return sorted(
            (path for path in self.folder.glob("*.sav")
             if path.is_file() and path.name.casefold() not in existing_names),
            key=lambda path: path.name.casefold(),
        )

    def _wait_for_state(self, existing_names, stage, kind, vk_code):
        deadline = time.monotonic() + SAVE_TIMEOUT_SECONDS
        stable_path = None
        stable_size = None
        stable_since = None

        while True:
            now = time.monotonic()
            candidates = self._new_states(existing_names)
            if len(candidates) > 1:
                raise CheckpointSaveError(
                    f"Multiple new .sav files appeared for stage {stage} {kind}."
                )
            if not candidates:
                stable_path = stable_size = stable_since = None
            else:
                path = candidates[0]
                try:
                    size = path.stat().st_size
                except OSError:
                    stable_path = stable_size = stable_since = None
                else:
                    if size <= MIN_STABLE_SIZE:
                        stable_path, stable_size, stable_since = path, size, None
                    elif path != stable_path or size != stable_size or stable_since is None:
                        stable_path, stable_size, stable_since = path, size, now
                    elif now - stable_since >= STABLE_SECONDS:
                        try:
                            data = path.read_bytes()
                            final_size = path.stat().st_size
                        except OSError:
                            stable_path = stable_size = stable_since = None
                        else:
                            if len(data) == size == final_size:
                                return path, data
                            stable_path = path
                            stable_size = final_size
                            stable_since = now if final_size > MIN_STABLE_SIZE else None

            if now >= deadline:
                raise CheckpointSaveError(
                    f"No single new stable .sav file appeared for stage {stage} {kind} "
                    f"after VK {vk_code:#04x}."
                )
            time.sleep(POLL_INTERVAL_SECONDS)

    def _failed(self, stage, kind, tick, score, vk_code, error):
        self.record("checkpoint_save_failed", stage=stage, kind=kind, tick=tick,
                    score=score, vk_code=vk_code, error=str(error))
        if isinstance(error, CheckpointSaveError):
            raise error
        raise CheckpointSaveError(
            f"Checkpoint save failed for stage {stage} {kind}: {error}"
        ) from error

    def save(self, stage, kind, tick, score=None):
        """Save one checkpoint, returning its manifest or a prior saved one."""
        identity = self._identity(stage, kind)
        if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
            raise ValueError("tick must be a nonnegative integer")
        if score is not None and (isinstance(score, bool) or not isinstance(score, int)):
            raise ValueError("score must be an integer or None")

        if identity in self.saved:
            return dict(self.saved[identity])
        if identity in self._attempted:
            raise CheckpointSaveError(
                f"Checkpoint stage {stage} {kind} was already attempted; hotkey will not be retried."
            )

        vk_code = self._hotkey(stage, kind)
        existing_names = {path.name.casefold() for path in self.folder.glob("*.sav")}
        self._attempted.add(identity)
        self.record("checkpoint_save_requested", stage=stage, kind=kind, tick=tick,
                    score=score, vk_code=vk_code)
        try:
            if not self.key(vk_code):
                raise CheckpointSaveError(f"Key event VK {vk_code:#04x} was not posted.")
            state_path, data = self._wait_for_state(existing_names, stage, kind, vk_code)
            manifest = {
                "path": str(state_path),
                "stage": stage,
                "kind": kind,
                "tick": tick,
                "score": score,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            manifest_path = self.folder / f"checkpoint-stage{stage}-{kind}.json"
            with manifest_path.open("x", encoding="utf-8") as stream:
                json.dump(manifest, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
        except Exception as exc:
            self._failed(stage, kind, tick, score, vk_code, exc)

        self.saved[identity] = manifest
        self.record("checkpoint_saved", **manifest)
        return dict(manifest)
