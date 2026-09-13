"""Asynchronous, in-memory audio preparation for the Learn Sounds menu."""

from pathlib import Path
import threading

import audio_devices
from duckstation_audio_output import WasapiCueOutput
from duckstation_cues import (
    BUTTONS, PAN_POSITIONS, _apply_prepared_volume,
    load_handoff_wav, preprocess_wav,
)


class PracticeSounds:
    """Prepare the Learn Sounds output off the UI thread and play on request."""

    def __init__(self, root, preference, panned, volume, on_error=None):
        self.root = Path(root)
        self.preference = preference
        self.panned = bool(panned)
        self.volume = int(volume)
        self.on_error = on_error
        self.error = None
        self._condition = threading.Condition()
        self._pending = None
        self._output = None
        self._ready = False
        self._closed = False
        self._started = False
        self._thread = threading.Thread(
            target=self._run, name="parappa-sound-practice", daemon=True)

    @property
    def ready(self):
        with self._condition:
            return self._ready

    @property
    def closed(self):
        with self._condition:
            return self._closed

    def start(self):
        with self._condition:
            if not self._started and not self._closed:
                self._started = True
                self._thread.start()
        return self

    def _prepare(self):
        output_name = audio_devices.resolve_preference(self.preference)
        if not output_name:
            raise RuntimeError("Choose an audio device in Settings before learning sounds.")
        prepared = {}
        for button in BUTTONS:
            with self._condition:
                if self._closed:
                    return None
            source = (self.root / "sounds" / f"{button.lower()}.wav").read_bytes()
            pan = PAN_POSITIONS[button] if self.panned else None
            cue = preprocess_wav(source, pan=pan)
            prepared[button] = _apply_prepared_volume(cue, self.volume).wav_bytes
        handoff = preprocess_wav(load_handoff_wav(self.root)[0])
        handoff = _apply_prepared_volume(handoff, self.volume).wav_bytes
        with self._condition:
            if self._closed:
                return None
        return WasapiCueOutput(output_name, prepared, handoff)

    def _run(self):
        output = None
        callback_error = None
        try:
            output = self._prepare()
            if output is None:
                return
            with self._condition:
                if self._closed:
                    return
                self._output = output
                self._ready = True
                self._condition.notify_all()
                while not self._closed:
                    while self._pending is None and not self._closed:
                        self._condition.wait()
                    if self._closed:
                        break
                    kind, value = self._pending
                    self._pending = None
                    if kind == "stop":
                        output.stop()
                    elif kind == "handoff":
                        output.play_handoff()
                    else:
                        output.play(value)
        except Exception as error:
            with self._condition:
                self.error = str(error)
                self._pending = None
                callback_error = None if self._closed else self.error
        finally:
            if output is not None:
                try:
                    output.close()
                except Exception:
                    pass
            callback = self.on_error if callback_error is not None else None
            if callback is not None:
                try:
                    callback(callback_error)
                except Exception:
                    pass
            with self._condition:
                self._output = None
                self._ready = False
                self._condition.notify_all()

    def _request(self, request):
        with self._condition:
            if self._closed or self.error or not self._started:
                return {"result": False, "status": "unavailable"}
            self._pending = request
            self._condition.notify_all()
        return {"result": True, "status": "submitted"}

    def play(self, button):
        if button not in BUTTONS:
            return {"result": False, "status": "unknown cue"}
        return self._request(("button", button))

    def play_handoff(self):
        return self._request(("handoff", None))

    def stop(self):
        with self._condition:
            if self._started and not self._closed and not self.error:
                self._pending = ("stop", None)
                self._condition.notify_all()

    def close(self, wait=True):
        with self._condition:
            self._closed = True
            self._pending = None
            self._condition.notify_all()
        if wait and self._started and self._thread is not threading.current_thread():
            self._thread.join()
