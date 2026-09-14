"""Local preferences for the accessible launcher.

The JSON file lives below ignored ``logs/`` so it stays per-user and is never
packaged as project source. The legacy panning marker is read once when the new
file does not exist; it is still written by the launcher for the Lua cue path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "logs" / "accessibility-settings.json"
LEGACY_PANNING_PATH = ROOT / "logs" / "demo-panning.txt"

# ``None`` follows the Windows WASAPI system default; an explicit saved name
# continues to select that exact supported output.
DEFAULT_AUDIO_OUTPUT = None


def default_settings() -> dict[str, object]:
    return {
        "panned_cues": True,
        "audio_output": DEFAULT_AUDIO_OUTPUT,
        "handoff_sound": True,
        "cue_volume": 100,
        "diagnostics": False,
    }


def _legacy_panning(path: Path) -> bool:
    try:
        value = path.read_text(encoding="ascii").strip().lower()
    except (OSError, UnicodeError):
        return True
    if value == "off":
        return False
    if value == "on":
        return True
    return True


def save_settings(settings: dict[str, object], path: Path = SETTINGS_PATH) -> None:
    """Atomically write only the supported preference fields."""
    path = Path(path)
    panned = settings.get("panned_cues")
    output = settings.get("audio_output")
    handoff_sound = settings.get("handoff_sound", True)
    cue_volume = settings.get("cue_volume", 100)
    diagnostics = settings.get("diagnostics", False)
    if type(diagnostics) is not bool:
        raise ValueError("diagnostics must be a boolean")
    if type(panned) is not bool:
        raise ValueError("panned_cues must be a boolean")
    if output is not None and (not isinstance(output, str) or not output.strip()):
        raise ValueError("audio_output must be a non-empty device name or None")
    if type(handoff_sound) is not bool:
        raise ValueError("handoff_sound must be a boolean")
    if type(cue_volume) is not int or not 0 <= cue_volume <= 200:
        raise ValueError("cue_volume must be an integer from 0 to 200")
    normalized = {
        "schema_version": 1,
        "panned_cues": panned,
        "audio_output": output.strip() if isinstance(output, str) else None,
        "handoff_sound": handoff_sound,
        "cue_volume": cue_volume,
        "diagnostics": diagnostics,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(normalized, stream, indent=2)
            stream.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_settings(
    path: Path = SETTINGS_PATH,
    legacy_panning_path: Path = LEGACY_PANNING_PATH,
) -> dict[str, object]:
    """Load preferences, migrating the old panning marker on first run."""
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        settings = default_settings()
        settings["panned_cues"] = _legacy_panning(Path(legacy_panning_path))
        # Creating this ignored local file makes first-run defaults durable.
        save_settings(settings, path)
        return settings
    except OSError:
        return default_settings()

    try:
        decoded = json.loads(raw)
    except (ValueError, TypeError):
        # Keep a malformed existing file intact; a later explicit preference
        # change can replace it with a valid version.
        return default_settings()

    defaults = default_settings()
    if not isinstance(decoded, dict):
        return defaults
    panned = decoded.get("panned_cues", defaults["panned_cues"])
    output = decoded.get("audio_output", defaults["audio_output"])
    handoff_sound = decoded.get("handoff_sound", defaults["handoff_sound"])
    cue_volume = decoded.get("cue_volume", defaults["cue_volume"])
    diagnostics = decoded.get("diagnostics", False)
    if type(diagnostics) is not bool:
        diagnostics = False
    if type(panned) is not bool:
        panned = defaults["panned_cues"]
    if output is not None and (not isinstance(output, str) or not output.strip()):
        output = defaults["audio_output"]
    if type(handoff_sound) is not bool:
        handoff_sound = defaults["handoff_sound"]
    if type(cue_volume) is not int or not 0 <= cue_volume <= 200:
        cue_volume = defaults["cue_volume"]
    return {
        "panned_cues": panned,
        "audio_output": output.strip() if isinstance(output, str) else None,
        "handoff_sound": handoff_sound,
        "cue_volume": cue_volume,
        "diagnostics": diagnostics,
    }
