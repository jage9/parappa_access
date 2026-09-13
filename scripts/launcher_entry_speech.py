"""Prism speech for launcher entry announcements, without console fallback."""
from pathlib import Path
import sys
import threading


ROOT = Path(__file__).resolve().parents[1]
PRISM_PATH = ROOT / 'tools' / 'prism-python'


class EntrySpeech:
    """Lazily speak menu entry announcements through Prism when available."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.context = None
        self.backend = None
        self._initialized = False
        self._lock = threading.RLock()

    def _get_backend(self):
        if not self.enabled or self._initialized:
            return self.backend

        self._initialized = True
        prism_path = str(PRISM_PATH)
        if prism_path not in sys.path:
            sys.path.insert(0, prism_path)
        try:
            import prism

            self.context = prism.Context()
            self.backend = self.context.create_best()
        except Exception:
            self.context = None
            self.backend = None
        return self.backend

    def say(self, text):
        """Speak once if Prism is available; never print duplicate console text."""
        if not self.enabled:
            return False
        with self._lock:
            backend = self._get_backend()
            if backend is None:
                return False
            try:
                backend.speak(text, interrupt=True)
            except Exception:
                self.backend = None
                return False
            return True

    def stop(self):
        """Stop Prism speech if it was initialized, swallowing backend errors."""
        with self._lock:
            backend = self.backend
            if backend is None:
                return False
            try:
                backend.stop()
            except Exception:
                return False
            return True
