"""Make source and developer modules importable from unittest discovery."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "scripts", ROOT / "developer"):
    if directory.is_dir() and str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
