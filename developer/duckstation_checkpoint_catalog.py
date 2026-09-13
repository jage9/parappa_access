"""Read and validate saved DuckStation campaign checkpoints."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


_MANIFEST_NAME = re.compile(
    r"checkpoint-stage([0-9]+)-([a-z]+)\.json", re.IGNORECASE
)
_SHA256 = re.compile(r"[0-9a-f]{64}", re.IGNORECASE)
_KINDS = {"entry", "clear", "ending"}


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _checkpoint_root(root) -> Path:
    return Path(root).resolve() / "logs" / "duck-checkpoints"


def _resolve_manifest(manifest_path, root) -> tuple[Path, Path]:
    project_root = Path(root).resolve()
    manifest = Path(manifest_path)
    if not manifest.is_absolute():
        manifest = project_root / manifest
    try:
        manifest = manifest.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"Checkpoint manifest is unavailable: {manifest}: {exc}") from exc

    checkpoint_root = _checkpoint_root(project_root)
    if not _inside(manifest, checkpoint_root):
        raise ValueError(f"Checkpoint manifest must be under {checkpoint_root}: {manifest}")
    relative = manifest.relative_to(checkpoint_root)
    if len(relative.parts) != 2 or not manifest.is_file():
        raise ValueError("Checkpoint manifest must be directly inside a session folder")
    if _MANIFEST_NAME.fullmatch(manifest.name) is None:
        raise ValueError(f"Unsupported checkpoint manifest name: {manifest.name}")
    return manifest, checkpoint_root


def load_checkpoint(manifest_path, root) -> dict:
    """Load one valid checkpoint manifest and verify its read-only save file.

    Relative manifest paths are rooted at ``root``. The manifest's ``path`` may
    be absolute or session-relative, but its resolved target must stay inside
    the manifest's session directory. The returned ``path`` is always absolute.
    """
    manifest_path, _ = _resolve_manifest(manifest_path, root)
    try:
        with manifest_path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read checkpoint manifest {manifest_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Checkpoint manifest must contain a JSON object")

    stage = data.get("stage")
    if isinstance(stage, bool) or not isinstance(stage, int) or not 1 <= stage <= 6:
        raise ValueError("Checkpoint stage must be an integer from 1 through 6")
    kind = data.get("kind")
    if not isinstance(kind, str) or kind not in _KINDS:
        raise ValueError("Checkpoint kind must be 'entry', 'clear', or 'ending'")
    if kind == "ending" and stage != 6:
        raise ValueError("An ending checkpoint is only valid for stage 6")
    expected_name = f"checkpoint-stage{stage}-{kind}.json"
    if manifest_path.name.casefold() != expected_name.casefold():
        raise ValueError("Checkpoint manifest filename does not match its stage and kind")

    tick = data.get("tick")
    if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
        raise ValueError("Checkpoint tick must be a nonnegative integer")
    score = data.get("score")
    if score is not None and (isinstance(score, bool) or not isinstance(score, int)):
        raise ValueError("Checkpoint score must be an integer or null")

    save_value = data.get("path")
    if not isinstance(save_value, str) or not save_value.strip():
        raise ValueError("Checkpoint path must be a nonempty string")
    save_path = Path(save_value)
    if not save_path.is_absolute():
        save_path = manifest_path.parent / save_path
    try:
        save_path = save_path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"Checkpoint save file is unavailable: {save_value}: {exc}") from exc
    if not _inside(save_path, manifest_path.parent):
        raise ValueError("Checkpoint save file must resolve inside its manifest session folder")
    if save_path.suffix.casefold() != ".sav" or not save_path.is_file():
        raise ValueError("Checkpoint path must name an existing .sav file")

    size = data.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError("Checkpoint size must be a nonnegative integer")
    expected_digest = data.get("sha256")
    if not isinstance(expected_digest, str) or _SHA256.fullmatch(expected_digest) is None:
        raise ValueError("Checkpoint sha256 must contain 64 hexadecimal characters")

    digest = hashlib.sha256()
    actual_size = 0
    try:
        with save_path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                actual_size += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"Cannot read checkpoint save file {save_path}: {exc}") from exc
    if actual_size != size:
        raise ValueError(
            f"Checkpoint size mismatch for {save_path}: manifest has {size}, file has {actual_size}"
        )
    if digest.hexdigest().casefold() != expected_digest.casefold():
        raise ValueError(f"Checkpoint SHA-256 mismatch for {save_path}")

    result = dict(data)
    result["path"] = str(save_path)
    result["manifest_path"] = str(manifest_path)
    return result


def list_checkpoints(root, *, errors=None) -> list[dict]:
    """Return valid checkpoint metadata in stable stage/kind order.

    Only ``logs/duck-checkpoints/<session>/checkpoint-stageN-kind.json`` files
    are considered. Other session JSON, including provenance, is ignored. If
    ``errors`` is a list, skipped checkpoint manifests are recorded there as
    dictionaries containing their absolute ``path`` and a readable ``error``.
    """
    checkpoint_root = _checkpoint_root(root)
    if not checkpoint_root.is_dir():
        return []

    checkpoints = []
    for session in sorted(checkpoint_root.iterdir(), key=lambda path: path.name.casefold()):
        if not session.is_dir():
            continue
        for manifest in sorted(session.glob("checkpoint-stage*.json"),
                               key=lambda path: path.name.casefold()):
            if _MANIFEST_NAME.fullmatch(manifest.name) is None:
                continue
            try:
                checkpoints.append(load_checkpoint(manifest, root))
            except (OSError, ValueError) as exc:
                if errors is not None:
                    errors.append({"path": str(manifest.resolve()), "error": str(exc)})

    order = {"entry": 0, "clear": 1, "ending": 2}
    return sorted(checkpoints,
                  key=lambda checkpoint: (checkpoint["stage"], order[checkpoint["kind"]],
                                          checkpoint["path"].casefold()))
