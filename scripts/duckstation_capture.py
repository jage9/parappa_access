"""Bounded DuckStation playback and foreground keyboard capture helpers.

Keyboard times are receipts from a Windows WH_KEYBOARD_LL hook. They are not
emulator callback times or measurements of physical key-switch time.
"""
from __future__ import annotations

import ctypes
import datetime
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

from duckstation_keyboard import HINT_VK, LYRICS_VK, RATING_VK, SCORE_VK


ROOT = Path(__file__).resolve().parents[1]
RECORDER_SCRIPT = ROOT / "developer" / "record-timing-audio.py"
DEFAULT_AUDIO_SECONDS = 180
MAX_AUDIO_SECONDS = 900
READY_MARKER = "TIMING_RECORDING"
KEY_MAP = {
    0x49: ("I", "Triangle"),
    0x4C: ("L", "Circle"),
    0x4B: ("K", "Cross"),
    0x4A: ("J", "Square"),
    0x51: ("Q", "L1"),
    0x45: ("E", "R1"),
}
HELPER_KEY_MAP = {
    SCORE_VK: ("Z", "score"),
    RATING_VK: ("X", "rating"),
    HINT_VK: ("Slash", "hint"),
    LYRICS_VK: ("Y", "lyrics"),
}
KEYBOARD_CLOCK_LABEL = (
    "Windows WH_KEYBOARD_LL OS hook receipt; not emulator callback time "
    "or physical key-switch time"
)
LLKHF_LOWER_IL_INJECTED = 0x0002
LLKHF_INJECTED = 0x0010
_EVENT_NAME = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")

# User-attached reports retain readable game, cue, menu, score, and keyboard
# events while excluding raw RAM, stack, instruction, and settings dumps.
_PUBLIC_EVENT_FIELDS = {
    "stage_context": ("valid", "stage", "app", "mode"),
    "cursor_consumed": ("cursor", "button", "lane", "index", "tick", "mode", "active"),
    "cue_submission": ("button", "cursor", "lane", "index", "tick", "detected_ns", "before_ns", "after_ns", "result", "status"),
    "cue_suppressed": ("button", "cursor", "lane", "index", "tick", "reason", "gap_ns"),
    "handoff_visible": ("stage", "tick", "frame", "kind"),
    "handoff_submission": ("stage", "tick", "frame", "kind", "before_ns", "after_ns", "result", "status"),
    "rating_changed": ("rating", "stage"),
    "rating_requested": ("rating", "stage"),
    "score_requested": ("score",),
    "round_score": ("stage", "score", "reason"),
    "retry_dialog_entered": ("score",),
    "menu_speech": ("text", "hint"),
    "scene_speech": ("stage", "scene", "text"),
    "subtitle_speech": ("text", "kind", "stage"),
    "lyric_suppressed": ("text", "reason", "stage"),
    "lyrics_toggled": ("enabled",),
    "monitor_summary": ("polls", "unstable_reads", "game_tick_changes", "cue_submissions", "poll_gaps", "read_cost"),
    "observation_limit": ("seconds", "gameplay_and_cues_continue"),
    "clock_discontinuity": ("previous_tick", "tick"),
    "state_stalled": ("tick",),
    "monitor_error": (),
    "emulator_closed": (),
    "resume_requested": ("debugger_detach",),
}


class CaptureStartupError(RuntimeError):
    """Raised when the playback recorder or keyboard hook cannot start."""


class NullCapture:
    """No-op event sink for ordinary play when diagnostics are disabled."""

    diagnostics_enabled = False
    enabled = False
    session_dir = None

    def __init__(self, target_pid=None):
        self.target_pid = target_pid

    def start(self):
        return self

    def set_armed(self, armed):
        if not isinstance(armed, bool):
            raise TypeError("armed must be an explicit bool.")

    def record_event(self, event_name, **fields):
        return False

    def stop(self):
        return None


def filter_key_event(
    vk_code: int,
    edge: str,
    *,
    armed: bool,
    foreground_pid: int,
    target_pid: int,
    ctrl_down: bool = False,
    alt_down: bool = False,
    win_down: bool = False,
    repeat: bool = False,
    raw_flags: int = 0,
    perf_counter_ns: int,
    windows_event_time_ms: int,
) -> dict | None:
    """Return a small record only for an armed, focused, unmodified mapped key.

    This pure filter deliberately receives both clock values from its caller so
    tests can verify the capture gates without installing a Windows hook.
    """
    if armed is not True or not target_pid or foreground_pid != target_pid:
        return None
    if ctrl_down or alt_down or win_down or repeat:
        return None
    if edge not in ("down", "up"):
        return None

    button_entry = KEY_MAP.get(vk_code)
    helper_entry = HELPER_KEY_MAP.get(vk_code)
    if button_entry is None and helper_entry is None:
        return None

    key, label = button_entry if button_entry is not None else helper_entry
    record = {
        "event": "keyboard" if button_entry is not None else "keyboard_helper",
        "source": "windows_wh_keyboard_ll",
        "edge": edge,
        "key": key,
        "vk_code": int(vk_code),
        "injected": bool(raw_flags & LLKHF_INJECTED),
        "lower_integrity_injected": bool(raw_flags & LLKHF_LOWER_IL_INJECTED),
        "raw_flags": int(raw_flags),
        "perf_counter_ns": int(perf_counter_ns),
        "windows_event_time_ms": int(windows_event_time_ms),
        "timestamp_basis": KEYBOARD_CLOCK_LABEL,
    }
    record["button" if button_entry is not None else "helper"] = label
    return record


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


class _WindowsKeyboardHook:
    """Install and remove WH_KEYBOARD_LL on a dedicated message-loop thread."""

    WH_KEYBOARD_LL = 13
    HC_ACTION = 0
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    WM_QUIT = 0x0012
    LLKHF_ALTDOWN = 0x0020

    def __init__(self, capture):
        self.capture = capture
        self._thread = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._startup_error = None
        self._hook_handle = None
        self._callback = None
        self._user32 = None
        self._kernel32 = None
        self._physical_down = set()
        self._captured_down = {}

    def start(self, timeout=5.0):
        if os.name != "nt":
            raise OSError("WH_KEYBOARD_LL capture requires Windows.")
        self._thread = threading.Thread(
            target=self._message_loop, name="duckstation-keyboard-hook", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            self.stop(timeout=2.0)
            raise TimeoutError("Keyboard hook did not become ready.")
        if self._startup_error:
            self.stop(timeout=2.0)
            raise OSError(self._startup_error)

    def stop(self, timeout=3.0):
        thread = self._thread
        if thread is None:
            return True
        if thread.is_alive() and self._thread_id:
            try:
                if not self._user32.PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0):
                    # The thread may already be leaving its message loop.
                    pass
            except (AttributeError, OSError):
                pass
        thread.join(timeout=max(0.0, timeout))
        return not thread.is_alive()

    def _message_loop(self):
        try:
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            hook_proc_type = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t
            )
            self._configure_apis(hook_proc_type)

            class KBDLLHOOKSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("vkCode", ctypes.c_uint32),
                    ("scanCode", ctypes.c_uint32),
                    ("flags", ctypes.c_uint32),
                    ("time", ctypes.c_uint32),
                    ("dwExtraInfo", ctypes.c_size_t),
                ]

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", ctypes.c_void_p),
                    ("message", ctypes.c_uint32),
                    ("wParam", ctypes.c_size_t),
                    ("lParam", ctypes.c_ssize_t),
                    ("time", ctypes.c_uint32),
                    ("pt", POINT),
                    ("lPrivate", ctypes.c_uint32),
                ]

            def hook_proc(code, wparam, lparam):
                if code == self.HC_ACTION:
                    try:
                        data = ctypes.cast(
                            lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)
                        ).contents
                        self._handle_key(int(wparam), data)
                    except Exception:
                        # A Python exception must never escape a native hook.
                        self.capture._note_dropped_event()
                return self._user32.CallNextHookEx(
                    self._hook_handle, code, wparam, lparam
                )

            self._callback = hook_proc_type(hook_proc)
            self._thread_id = self._kernel32.GetCurrentThreadId()
            # Create the thread's message queue before the caller can post WM_QUIT.
            msg = MSG()
            self._user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
            module = self._kernel32.GetModuleHandleW(None)
            self._hook_handle = self._user32.SetWindowsHookExW(
                self.WH_KEYBOARD_LL, self._callback, module, 0
            )
            if not self._hook_handle:
                raise ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            while True:
                result = self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                self._user32.TranslateMessage(ctypes.byref(msg))
                self._user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self._startup_error = str(exc)
            self._ready.set()
        finally:
            if self._hook_handle:
                try:
                    self._user32.UnhookWindowsHookEx(self._hook_handle)
                except Exception:
                    pass
                self._hook_handle = None
            self._callback = None

    def _configure_apis(self, hook_proc_type):
        user32 = self._user32
        kernel32 = self._kernel32
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.GetWindowThreadProcessId.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)
        ]
        user32.GetWindowThreadProcessId.restype = ctypes.c_uint32
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.CallNextHookEx.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t
        ]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, hook_proc_type, ctypes.c_void_p, ctypes.c_uint32
        ]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = ctypes.c_bool
        user32.GetMessageW.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32
        ]
        user32.GetMessageW.restype = ctypes.c_int
        user32.PeekMessageW.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32
        ]
        user32.PeekMessageW.restype = ctypes.c_bool
        user32.TranslateMessage.argtypes = [ctypes.c_void_p]
        user32.TranslateMessage.restype = ctypes.c_bool
        user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
        user32.DispatchMessageW.restype = ctypes.c_ssize_t
        user32.PostThreadMessageW.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_ssize_t
        ]
        user32.PostThreadMessageW.restype = ctypes.c_bool
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = ctypes.c_uint32
        kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p

    def _foreground_pid(self):
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return 0
        pid = ctypes.c_uint32()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def _is_down(self, *virtual_keys):
        return any(self._user32.GetAsyncKeyState(key) & 0x8000 for key in virtual_keys)

    def _handle_key(self, message, data):
        if message in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
            edge = "down"
        elif message in (self.WM_KEYUP, self.WM_SYSKEYUP):
            edge = "up"
        else:
            return

        vk_code = int(data.vkCode)
        if vk_code not in KEY_MAP and vk_code not in HELPER_KEY_MAP:
            return
        receipt_ns = time.perf_counter_ns()
        repeat = vk_code in self._physical_down
        if edge == "down":
            self._physical_down.add(vk_code)
        else:
            self._physical_down.discard(vk_code)

        armed, arm_generation = self.capture._get_arm_state()
        captured_generation = None
        if edge == "up":
            captured_generation = self._captured_down.pop(vk_code, None)
            if captured_generation != arm_generation:
                return

        # System key messages indicate Alt involvement; GetAsyncKeyState catches
        # modifiers whether or not Windows reports the key as a system event.
        alt_from_event = message in (self.WM_SYSKEYDOWN, self.WM_SYSKEYUP) or bool(
            data.flags & self.LLKHF_ALTDOWN
        )
        event = filter_key_event(
            vk_code,
            edge,
            armed=armed,
            foreground_pid=self._foreground_pid(),
            target_pid=self.capture.target_pid,
            ctrl_down=self._is_down(0x11, 0xA2, 0xA3),
            alt_down=alt_from_event or self._is_down(0x12, 0xA4, 0xA5),
            win_down=self._is_down(0x5B, 0x5C),
            repeat=(repeat if edge == "down" else False),
            raw_flags=int(data.flags),
            perf_counter_ns=receipt_ns,
            windows_event_time_ms=int(data.time),
        )
        if event is None:
            return
        if self.capture._enqueue(event) and edge == "down":
            self._captured_down[vk_code] = arm_generation


class DuckStationCapture:
    """Write bounded text diagnostics and optionally capture loopback audio."""

    def __init__(
        self,
        session_dir,
        target_pid,
        loopback_name="ProFX 1-2 (ProFX) [Loopback]",
        *,
        event_cap=4096,
        queue_size=512,
        ready_timeout=8.0,
        audio_seconds=DEFAULT_AUDIO_SECONDS,
        session_metadata=None,
        popen_factory=None,
        hook_factory=None,
        hook_enabled=True,
        record_audio=True,
        public_diagnostics=False,
    ):
        if not isinstance(target_pid, int) or isinstance(target_pid, bool) or target_pid <= 0:
            raise ValueError("target_pid must be a positive process ID.")
        if record_audio and (not isinstance(loopback_name, str) or not loopback_name.strip()):
            raise ValueError("loopback_name must be the exact playback-loopback device name.")
        if not isinstance(record_audio, bool) or not isinstance(public_diagnostics, bool):
            raise TypeError("record_audio and public_diagnostics must be bool values.")
        if public_diagnostics and record_audio:
            raise ValueError("Public diagnostics must not record playback audio.")
        if not isinstance(event_cap, int) or isinstance(event_cap, bool) or event_cap < 1:
            raise ValueError("event_cap must be a positive integer.")
        if not isinstance(queue_size, int) or isinstance(queue_size, bool) or queue_size < 1:
            raise ValueError("queue_size must be a positive integer.")
        if not 0 < float(ready_timeout) <= 60:
            raise ValueError("ready_timeout must be between 0 and 60 seconds.")
        if not isinstance(audio_seconds, (int, float)) or isinstance(audio_seconds, bool):
            raise ValueError(f"audio_seconds must be a number between 0 and {MAX_AUDIO_SECONDS}.")
        try:
            audio_seconds = float(audio_seconds)
        except OverflowError as exc:
            raise ValueError(
                f"audio_seconds must be greater than 0 and at most {MAX_AUDIO_SECONDS}."
            ) from exc
        if not math.isfinite(audio_seconds) or not 0 < audio_seconds <= MAX_AUDIO_SECONDS:
            raise ValueError(f"audio_seconds must be greater than 0 and at most {MAX_AUDIO_SECONDS}.")
        if session_metadata is not None and not isinstance(session_metadata, dict):
            raise TypeError("session_metadata must be a dictionary.")

        self.session_dir = Path(session_dir).resolve()
        logs_root = (ROOT / "logs").resolve()
        if not self.session_dir.is_relative_to(logs_root):
            raise ValueError("Capture outputs must be inside the ignored logs directory.")
        self.target_pid = target_pid
        self.loopback_name = loopback_name
        self.record_audio = record_audio
        self.public_diagnostics = public_diagnostics
        self.diagnostics_enabled = True
        self.enabled = True
        self.event_cap = event_cap
        self.queue_size = min(queue_size, event_cap)
        self.ready_timeout = float(ready_timeout)
        self.audio_seconds = int(audio_seconds) if audio_seconds.is_integer() else audio_seconds
        self.session_metadata = dict(session_metadata or {})
        self._popen = popen_factory or subprocess.Popen
        self._hook_factory = hook_factory or _WindowsKeyboardHook
        self._hook_enabled = bool(hook_enabled)

        self.manifest_path = self.session_dir / "manifest.json"
        self.events_path = self.session_dir / "events.jsonl"
        self.audio_path = self.session_dir / "playback.wav"
        self.audio_metadata_path = self.session_dir / "playback.json"
        self.recorder_log_path = self.session_dir / "playback-recorder.log"
        self.stop_file = self.session_dir / ("playback-" + uuid.uuid4().hex + ".stop")

        self._pending = queue.Queue(maxsize=self.queue_size)
        self._event_lock = threading.Lock()
        self._arm_lock = threading.Lock()
        self._armed = False
        self._arm_generation = 0
        self._accepting = False
        self._writer_stop = threading.Event()
        self._writer_thread = None
        self._event_file = None
        self._events_queued = 0
        self._events_written = 0
        self._dropped_events = 0
        self._writer_error = None
        self._recorder = None
        self._hook = None
        self._recorder_log = None
        self._started_utc = None
        self._stopped_utc = None
        self._status = "new"
        self._error = None
        self._cleanup_errors = []
        self._manifest_written = False

    @property
    def armed(self):
        return self._get_arm_state()[0]

    @property
    def dropped_events(self):
        with self._event_lock:
            return self._dropped_events

    @property
    def events_written(self):
        with self._event_lock:
            return self._events_written

    def _get_arm_state(self):
        with self._arm_lock:
            return self._armed, self._arm_generation

    def set_armed(self, armed):
        if not isinstance(armed, bool):
            raise TypeError("armed must be an explicit bool.")
        with self._arm_lock:
            if self._armed != armed:
                self._armed = armed
                self._arm_generation += 1

    def start(self):
        if self._status != "new":
            raise RuntimeError("Capture sessions can only be started once.")
        self.session_dir.mkdir(parents=True, exist_ok=True)
        paths = [self.manifest_path, self.events_path]
        if self.record_audio:
            paths.extend((self.audio_path, self.audio_metadata_path,
                          self.recorder_log_path, self.stop_file))
        existing = [path.name for path in paths if path.exists()]
        if existing:
            raise FileExistsError("Capture output already exists: " + ", ".join(existing))
        self._started_utc = _utc_now()
        self._status = "starting"
        self._write_manifest()
        try:
            self._event_file = self.events_path.open(
                "x", encoding="utf-8", buffering=1, newline="\n"
            )
            self._accepting = True
            self._writer_thread = threading.Thread(
                target=self._writer_loop, name="duckstation-capture-jsonl", daemon=True
            )
            self._writer_thread.start()
            if self.record_audio:
                self._start_recorder()
            if self._hook_enabled:
                self._hook = self._hook_factory(self)
                self._hook.start()
            self._status = "recording"
            self._write_manifest()
            return self
        except Exception as exc:
            self._error = str(exc)
            self._status = "startup_failed"
            self.set_armed(False)
            if self._hook is not None:
                try:
                    if not self._hook.stop():
                        self._cleanup_errors.append("Keyboard hook thread did not stop.")
                except Exception as cleanup_exc:
                    self._cleanup_errors.append(str(cleanup_exc))
            self._stop_recorder()
            self._stop_writer()
            self._stopped_utc = _utc_now()
            self._write_manifest()
            if isinstance(exc, CaptureStartupError):
                raise
            raise CaptureStartupError(str(exc)) from exc

    def record_event(self, event_name, *, source="host_monitor", perf_counter_ns=None, **fields):
        """Queue one monitor event; this method performs no file I/O."""
        if not isinstance(event_name, str) or not _EVENT_NAME.fullmatch(event_name):
            raise ValueError("event_name must be a short alphanumeric event label.")
        if not isinstance(source, str) or not _EVENT_NAME.fullmatch(source):
            raise ValueError("source must be a short alphanumeric label.")
        reserved = {"event", "source", "perf_counter_ns"}.intersection(fields)
        if reserved:
            raise ValueError("reserved event fields: " + ", ".join(sorted(reserved)))
        stamp = time.perf_counter_ns() if perf_counter_ns is None else perf_counter_ns
        if not isinstance(stamp, int) or isinstance(stamp, bool):
            raise TypeError("perf_counter_ns must be an integer.")
        if self.public_diagnostics:
            allowed = _PUBLIC_EVENT_FIELDS.get(event_name)
            if allowed is None:
                return False
            fields = {name: fields[name] for name in allowed if name in fields}
        record = {
            "event": event_name,
            "source": source,
            "perf_counter_ns": stamp,
            **fields,
        }
        return self._enqueue(record)

    def _enqueue(self, record):
        with self._event_lock:
            if not self._accepting:
                return False
            if self._events_queued >= self.event_cap:
                self._dropped_events += 1
                return False
            try:
                self._pending.put_nowait(record)
            except queue.Full:
                self._dropped_events += 1
                return False
            self._events_queued += 1
            return True

    def _note_dropped_event(self):
        with self._event_lock:
            self._dropped_events += 1

    def _writer_loop(self):
        try:
            while not self._writer_stop.is_set() or not self._pending.empty():
                try:
                    record = self._pending.get(timeout=0.05)
                except queue.Empty:
                    continue
                try:
                    if self._writer_error is not None:
                        with self._event_lock:
                            self._dropped_events += 1
                        continue
                    line = json.dumps(record, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
                    self._event_file.write(line + "\n")
                    with self._event_lock:
                        self._events_written += 1
                        written = self._events_written
                    if written % 16 == 0:
                        self._event_file.flush()
                except Exception as exc:
                    self._writer_error = str(exc)
                    with self._event_lock:
                        self._dropped_events += 1
                finally:
                    self._pending.task_done()
        finally:
            if self._event_file is not None:
                try:
                    self._event_file.flush()
                    self._event_file.close()
                except Exception as exc:
                    self._writer_error = self._writer_error or str(exc)
                self._event_file = None

    def _start_recorder(self):
        command = [
            sys.executable,
            "-I",
            "-S",
            str(RECORDER_SCRIPT),
            "--output",
            str(self.audio_path),
            "--seconds",
            str(self.audio_seconds),
            "--stop-file",
            str(self.stop_file),
            "--loopback-name",
            self.loopback_name,
        ]
        try:
            self._recorder_log = self.recorder_log_path.open("x", encoding="utf-8")
            self._recorder = self._popen(
                command,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=self._recorder_log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise CaptureStartupError(f"Playback capture could not start: {exc}") from exc

        deadline = time.monotonic() + self.ready_timeout
        while time.monotonic() < deadline:
            if self._recorder.poll() is not None:
                raise CaptureStartupError("Playback capture exited before its ready marker.")
            try:
                if READY_MARKER in self.recorder_log_path.read_text(encoding="utf-8", errors="replace"):
                    return
            except OSError:
                pass
            time.sleep(0.05)
        raise CaptureStartupError("Playback capture did not become ready before the timeout.")

    def _stop_recorder(self):
        recorder = self._recorder
        if recorder is None:
            self._close_recorder_log()
            return
        try:
            if recorder.poll() is None:
                try:
                    with self.stop_file.open("xb"):
                        pass
                except FileExistsError:
                    pass
                except OSError as exc:
                    self._cleanup_errors.append(f"Could not signal recorder stop: {exc}")
                try:
                    recorder.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._cleanup_errors.append("Recorder did not stop on request; terminating recorder only.")
                    try:
                        recorder.terminate()
                    except OSError as exc:
                        self._cleanup_errors.append(f"Could not terminate recorder: {exc}")
                    try:
                        recorder.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:
                            recorder.kill()
                        except OSError as exc:
                            self._cleanup_errors.append(f"Could not kill recorder: {exc}")
                        try:
                            recorder.wait(timeout=3)
                        except (OSError, subprocess.TimeoutExpired) as exc:
                            self._cleanup_errors.append(f"Could not reap recorder: {exc}")
            else:
                recorder.wait(timeout=0)
        except (OSError, subprocess.SubprocessError) as exc:
            self._cleanup_errors.append(f"Could not clean up recorder: {exc}")
        finally:
            self._recorder = None
            self._close_recorder_log()

    def _close_recorder_log(self):
        log = self._recorder_log
        if log is not None:
            try:
                log.close()
            except OSError as exc:
                self._cleanup_errors.append(f"Could not close recorder log: {exc}")
            self._recorder_log = None

    def _stop_writer(self, timeout=5.0):
        with self._event_lock:
            self._accepting = False
        self._writer_stop.set()
        thread = self._writer_thread
        if thread is not None:
            thread.join(timeout=max(0.0, timeout))
            if thread.is_alive():
                self._cleanup_errors.append("Event writer did not stop before its timeout.")
                return False
        return True

    def stop(self):
        if self._status in ("stopped", "startup_failed"):
            return
        self.set_armed(False)
        if self._hook is not None:
            try:
                if not self._hook.stop():
                    self._cleanup_errors.append("Keyboard hook thread did not stop before its timeout.")
            except Exception as exc:
                self._cleanup_errors.append(f"Could not stop keyboard hook: {exc}")
            self._hook = None
        self._stop_recorder()
        self._stop_writer()
        self._stopped_utc = _utc_now()
        self._status = "stopped"
        self._write_manifest()

    def _manifest(self):
        with self._event_lock:
            event_stats = {
                "event_cap": self.event_cap,
                "queue_capacity": self.queue_size,
                "events_queued": self._events_queued,
                "events_written": self._events_written,
                "dropped_events": self._dropped_events,
            }
        armed, _ = self._get_arm_state()
        if self.public_diagnostics:
            return {
                "schema_version": 1,
                "capture_type": "duckstation_text_diagnostics",
                "status": self._status,
                "created_utc": self._started_utc,
                "stopped_utc": self._stopped_utc,
                "keyboard_capture": {
                    "enabled": self._hook_enabled,
                    "hook": "Windows WH_KEYBOARD_LL",
                    "ignored_modifiers": ["Ctrl", "Alt", "Win"],
                    "keys": {key: button for _, (key, button) in KEY_MAP.items()},
                    "helper_keys": {key: helper for _, (key, helper) in HELPER_KEY_MAP.items()},
                    "perf_counter_clock": "time.perf_counter_ns() at OS hook callback receipt",
                    "windows_event_time": "KBDLLHOOKSTRUCT.time in milliseconds",
                    "measurement_limit": KEYBOARD_CLOCK_LABEL,
                },
                "playback_capture": {"enabled": False, "microphone": False},
                "event_file": self.events_path.name,
                "event_stats": event_stats,
                "event_writer_error": bool(self._writer_error),
                "error": bool(self._error),
                "cleanup_errors": len(self._cleanup_errors),
            }
        return {
            "schema_version": 1,
            "capture_type": "duckstation_playback_and_keyboard_timing",
            "status": self._status,
            "session_directory": str(self.session_dir),
            "session_metadata": self.session_metadata,
            "created_utc": self._started_utc,
            "stopped_utc": self._stopped_utc,
            "target_pid": self.target_pid,
            "armed_at_manifest_write": armed,
            "keyboard_capture": {
                "hook": "Windows WH_KEYBOARD_LL",
                "requires_explicit_armed_flag": True,
                "requires_foreground_window_pid_equal_target_pid": True,
                "ignored_modifiers": ["Ctrl", "Alt", "Win"],
                "injection_flags": {
                    "injected": "KBDLLHOOKSTRUCT.flags bit 0x10",
                    "lower_integrity_injected": "KBDLLHOOKSTRUCT.flags bit 0x02",
                },
                "keys": {key: button for _, (key, button) in KEY_MAP.items()},
                "perf_counter_clock": "time.perf_counter_ns() at OS hook callback receipt",
                "windows_event_time": "KBDLLHOOKSTRUCT.time in milliseconds",
                "measurement_limit": KEYBOARD_CLOCK_LABEL,
            },
            "playback_capture": {
                "enabled": self.record_audio,
                "recorder_script": str(RECORDER_SCRIPT),
                "python_executable": sys.executable,
                "isolated_python_flags": ["-I", "-S"],
                "loopback_name": self.loopback_name,
                "max_seconds": self.audio_seconds,
                "microphone": False,
                "audio_file": self.audio_path.name,
                "metadata_file": self.audio_metadata_path.name,
                "recorder_log": self.recorder_log_path.name,
            },
            "event_file": self.events_path.name,
            "event_stats": event_stats,
            "event_writer_error": self._writer_error,
            "error": self._error,
            "cleanup_errors": list(self._cleanup_errors),
        }

    def _write_manifest(self):
        data = json.dumps(self._manifest(), indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        if not self._manifest_written:
            with self.manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(data)
            self._manifest_written = True
        else:
            self.manifest_path.write_text(data, encoding="utf-8", newline="\n")

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, traceback):
        self.stop()
        return False
