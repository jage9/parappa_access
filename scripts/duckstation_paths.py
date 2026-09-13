"""Resolve the DuckStation installation directory used by launcher tools."""
from pathlib import Path


EXECUTABLE_NAME = "duckstation-qt-x64-ReleaseLTCG.exe"
SETTINGS_NAME = "settings.ini"


def duckstation_directory(root):
    """Return the preferred DuckStation folder, keeping old installs usable.

    New releases use ``tools/duckstation``. Existing development installations
    may still be under ``tools/research/duckstation-stock/portable``; prefer
    that location until the simple folder contains an executable or settings
    file. If neither exists, return the simple location for first-time setup.
    """
    root = Path(root)
    preferred = root / "tools" / "duckstation"
    if ((preferred / EXECUTABLE_NAME).exists()
            or (preferred / SETTINGS_NAME).exists()):
        return preferred

    legacy = root / "tools" / "research" / "duckstation-stock" / "portable"
    if legacy.exists():
        return legacy
    return preferred
