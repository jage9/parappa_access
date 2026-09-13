"""Reusable asynchronous X-cue preview for the launcher's volume setting."""

from __future__ import annotations

from pathlib import Path
import threading

import audio_devices
from duckstation_audio_output import WasapiCueOutput
from duckstation_cues import preprocess_wav, _apply_prepared_volume


ROOT = Path(__file__).resolve().parents[1]
_VOLUMES = tuple(range(0, 201, 10))


def _source_stamp(path):
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size,
            getattr(stat, 'st_ino', None))


def _volume_key(volume):
    value = max(0, min(200, int(volume)))
    # Launcher settings move in ten-percent steps. Keep this helper tolerant
    # of a stale or manually edited value by selecting the nearest prepared cue.
    return min(200, max(0, ((value + 5) // 10) * 10))


def _output_key(preference, source_stamp):
    return preference, source_stamp


def _cue_name(volume):
    return f'VOLUME_{volume}'


def _prepared_cues(path):
    source = path.read_bytes()
    centered = preprocess_wav(source, pan=None)
    return {
        _cue_name(volume): _apply_prepared_volume(centered, volume).wav_bytes
        for volume in _VOLUMES
    }


def _close_output(output):
    if output is None:
        return
    try:
        output.stop()
    except Exception:
        pass
    try:
        output.close()
    except Exception:
        pass


class _PreviewWorker:
    """Own one reusable audio stream and coalesce pending volume requests."""

    def __init__(self):
        self.condition = threading.Condition()
        self.pending = None
        self.requested_key = None
        self.output = None
        self.output_key = None
        self.closed = False
        self.error = None
        self.error_key = None
        self.failed_key = None
        self.error_needs_signal = False
        self.error_signaled = False
        self.error_callback = None
        self.thread = threading.Thread(
            target=self._run, name='parappa-cue-preview', daemon=True)
        self.thread.start()

    def request(self, preference, source_path, source_stamp, volume, play,
                on_error=None, source_error=None):
        key = _output_key(preference, source_stamp)
        with self.condition:
            if self.closed:
                return
            if on_error is not None:
                self.error_callback = on_error
            if not play and self.requested_key == key:
                return  # Revisiting Settings must not cancel a pending device preview.
            self.requested_key = key
            if self.error_key is not None and self.error_key != key:
                self.error = None
                self.error_key = None
                self.failed_key = None
                self.error_needs_signal = False
                self.error_signaled = False
            self.pending = {
                'key': key,
                'preference': preference,
                'path': source_path,
                'volume': _volume_key(volume),
                'play': bool(play),
                'source_error': source_error,
            }
            if play and self.error is not None and self.error_key == key:
                # A silent warmup can fail. Hold its error until the user
                # requests a preview, then let the worker notify the UI.
                self.error_needs_signal = True
            self.condition.notify()

    def take_error(self):
        with self.condition:
            error = self.error
            self.error = None
            return error

    def _signal(self, callback):
        # The callback is only a notification hook; callers must marshal any
        # speech or window work back to their UI thread.
        try:
            callback()
        except Exception:
            pass

    def _save_error(self, error, request):
        callback = None
        with self.condition:
            if self.closed:
                return
            if self.pending is not None and self.pending['key'] != request['key']:
                # Do not report a stale failure if the user has already
                # selected a different device or the source file has changed.
                return
            self.error = str(error)
            self.error_key = request['key']
            self.failed_key = request['key']
            pending_play = (self.pending is not None
                            and self.pending['key'] == request['key']
                            and self.pending['play'])
            self.error_needs_signal = bool(request['play'] or pending_play)
            self.error_signaled = False
            if (self.error_needs_signal and self.error_callback is not None):
                self.error_signaled = True
                callback = self.error_callback
        if callback is not None:
            self._signal(callback)

    def _build_output(self, request):
        output_name = audio_devices.resolve_preference(request['preference'])
        if not output_name:
            raise RuntimeError('Choose an audio device to preview cue volume.')
        prepared_wavs = _prepared_cues(request['path'])
        return WasapiCueOutput(output_name, prepared_wavs)

    def _play_latest(self, output, key, request):
        callback_to_signal = None
        with self.condition:
            if self.closed:
                return False
            # A newer key means the request we just prepared is already stale.
            # Leave it pending so the next pass can replace the stream.
            if self.pending is not None:
                if self.pending['key'] != key:
                    return True
                request = self.pending
                self.pending = None
            if request['play']:
                try:
                    # Serialize play and close so no callback can submit audio
                    # after close_preview has taken effect.
                    output.play(_cue_name(request['volume']))
                except Exception as error:
                    self.error = str(error)
                    self.error_key = key
                    self.failed_key = key
                    self.error_needs_signal = True
                    self.error_signaled = self.error_callback is not None
                    callback_to_signal = self.error_callback
            still_open = not self.closed
        if callback_to_signal is not None:
            # This hook only posts work to the UI dispatcher in the caller.
            self._signal(callback_to_signal)
        return still_open

    def _run(self):
        output = None
        output_key = None
        try:
            while True:
                old_output_to_close = None
                with self.condition:
                    while self.pending is None and not self.closed:
                        self.condition.wait()
                    if self.closed:
                        break
                    request = self.pending
                    self.pending = None
                    key = request['key']

                    if self.error_key is not None and self.error_key != key:
                        self.error = None
                        self.error_key = None
                        self.failed_key = None
                        self.error_needs_signal = False
                        self.error_signaled = False

                    if self.failed_key == key:
                        if request['play'] and self.error is not None \
                                and not self.error_signaled \
                                and self.error_callback is not None:
                            self.error_signaled = True
                            callback = self.error_callback
                        else:
                            callback = None
                        reuse_failed = True
                    else:
                        callback = None
                        reuse_failed = False

                    if output is not None and output_key == key:
                        use_output = output
                    else:
                        use_output = None
                        old_output = output
                        output = None
                        output_key = None
                        if old_output is not None and self.output is old_output:
                            self.output = None
                            self.output_key = None
                        old_output_to_close = old_output

                if use_output is None and old_output_to_close is not None:
                    _close_output(old_output_to_close)
                if request['source_error'] is not None:
                    self._save_error(request['source_error'], request)
                    continue

                if callback is not None:
                    self._signal(callback)
                if reuse_failed:
                    continue

                # The launcher never queues previews: while a replacement is
                # prepared, pending requests collapse to the latest volume.
                if use_output is None:
                    with self.condition:
                        if self.closed:
                            break
                    try:
                        new_output = self._build_output(request)
                    except Exception as error:
                        self._save_error(error, request)
                        continue
                    with self.condition:
                        if self.closed:
                            should_close = True
                        else:
                            output = new_output
                            output_key = key
                            self.output = new_output
                            self.output_key = key
                            should_close = False
                    if should_close:
                        _close_output(new_output)
                        break
                    use_output = new_output

                if not self._play_latest(use_output, key, request):
                    break
        finally:
            with self.condition:
                final_output = output
                output = None
                self.output = None
                self.output_key = None
            _close_output(final_output)

    def close(self):
        with self.condition:
            if not self.closed:
                self.closed = True
                self.pending = None
                self.condition.notify_all()
        if self.thread is not threading.current_thread():
            # No sample-duration sleep is involved; this only waits for an
            # in-flight device open to notice cancellation and release itself.
            self.thread.join()


def _worker_for(menu):
    worker = getattr(menu, '_cue_preview_worker', None)
    if worker is None or worker.closed:
        worker = _PreviewWorker()
        menu._cue_preview_worker = worker
    return worker


def _submit(menu, play, on_error=None):
    source_path = ROOT / 'sounds' / 'x.wav'
    try:
        source_stamp = _source_stamp(source_path)
        stat_error = None
    except OSError as error:
        source_stamp = ('unavailable',)
        stat_error = error
    worker = _worker_for(menu)
    worker.request(menu.audio_output, source_path, source_stamp,
                   menu.cue_volume, play, on_error, stat_error)


def prepare_preview(menu, on_error=None):
    """Warm the selected device asynchronously without playing a cue."""
    _submit(menu, play=False, on_error=on_error)


def preview_volume(menu, on_error=None):
    """Request the latest volume preview without blocking menu navigation."""
    _submit(menu, play=True, on_error=on_error)


def take_preview_error(menu):
    """Return and clear a worker error for announcement on the UI thread."""
    worker = getattr(menu, '_cue_preview_worker', None)
    return worker.take_error() if worker is not None else None


def close_preview(menu):
    """Cancel pending playback and release the reusable stream and worker."""
    worker = getattr(menu, '_cue_preview_worker', None)
    if worker is None:
        return
    try:
        worker.close()
    finally:
        if getattr(menu, '_cue_preview_worker', None) is worker:
            delattr(menu, '_cue_preview_worker')
