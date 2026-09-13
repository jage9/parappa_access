"""Explicit developer-only DuckStation key driver; never imported by normal play."""
import ctypes


LANES = {
    1: ("I", 0x49, 0x10), 2: ("L", 0x4C, 0x20),
    3: ("K", 0x4B, 0x40), 4: ("J", 0x4A, 0x80),
    5: ("Q", 0x51, 0x04), 6: ("Q", 0x51, 0x04),
    7: ("E", 0x45, 0x08), 8: ("E", 0x45, 0x08),
}
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
MAX_HOLD_UPDATES, MAX_TICK_GAP = 6, 6
RELEASE_ATTEMPTS = 3


class _User32:
    def __init__(self):
        if not hasattr(ctypes, "windll"):
            raise OSError("The developer key driver requires Windows.")
        self.u = ctypes.windll.user32
        self.u.IsWindow.argtypes = [ctypes.c_void_p]
        self.u.IsWindow.restype = ctypes.c_bool
        self.u.IsWindowVisible.argtypes = [ctypes.c_void_p]
        self.u.IsWindowVisible.restype = ctypes.c_bool
        self.u.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        self.u.GetWindowThreadProcessId.restype = ctypes.c_ulong
        self.u.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
        self.u.MapVirtualKeyW.restype = ctypes.c_uint
        self.u.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        self.u.PostMessageW.restype = ctypes.c_bool

    def enum_windows(self):
        windows = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        @callback_type
        def visit(hwnd, _):
            windows.append(hwnd)
            return True
        self.u.EnumWindows(visit, None)
        return windows

    def is_window(self, hwnd): return bool(self.u.IsWindow(hwnd))
    def visible(self, hwnd): return bool(self.u.IsWindowVisible(hwnd))

    def window_pid(self, hwnd):
        pid = ctypes.c_ulong()
        self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def map_virtual_key(self, vk): return int(self.u.MapVirtualKeyW(vk, 0))
    def post_message(self, hwnd, msg, vk, lparam):
        return bool(self.u.PostMessageW(hwnd, msg, vk, lparam))


class Win32WindowBackend:
    """Post key messages to the unique visible top-level window owned by pid."""
    def __init__(self, pid, api=None):
        self.pid = int(pid)
        self.api = api or _User32()
        matches = [h for h in self.api.enum_windows()
                   if self.api.is_window(h) and self.api.visible(h) and self.api.window_pid(h) == self.pid]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one visible window for PID {self.pid}; found {len(matches)}")
        self.hwnd = matches[0]

    def key(self, vk, down):
        if (not self.api.is_window(self.hwnd) or self.api.window_pid(self.hwnd) != self.pid):
            return False
        scan = self.api.map_virtual_key(vk)
        if not 0 < scan <= 0xFF: return False
        lparam = 1 | (scan << 16)
        if vk in (0x25, 0x26, 0x27, 0x28): lparam |= 1 << 24
        if not down: lparam |= 3 << 30
        return self.api.post_message(self.hwnd, WM_KEYDOWN if down else WM_KEYUP, vk, lparam)


class DeveloperController:
    """Inject one scheduled lane at a time; pass a mock backend for pure tests."""
    def __init__(self, pid, schedule, offset_ticks=-6, backend=None):
        self.pid, self.offset = int(pid), int(offset_ticks)
        self.backend = backend or Win32WindowBackend(self.pid)
        if getattr(self.backend, "pid", self.pid) != self.pid:
            raise ValueError("Backend PID does not match the requested PID")
        self.schedule = []
        for target, lane in schedule:
            if isinstance(target, bool) or not isinstance(target, int) or target < 0 or lane not in LANES:
                raise ValueError(f"Invalid scheduled target/lane: {(target, lane)!r}")
            key, vk, mask = LANES[lane]
            self.schedule.append((target + self.offset, target, lane, key, vk, mask))
        self.schedule.sort(key=lambda row: row[0])
        self.index = 0
        self.last_tick = None
        self.active = None
        self.hold_updates = 0
        self.disabled = None
        self.closed = False

    def _release(self, reason, tick, attempts=1):
        if self.active is None: return []
        event = self.active
        posted = False
        error = None
        attempted = 0
        for attempted in range(1, max(1, attempts) + 1):
            try:
                posted = bool(self.backend.key(event["vk"], False))
            except Exception as exc:
                posted = False
                error = f"{type(exc).__name__}: {exc}"
            else:
                error = None
            if posted:
                self.active = None
                break
        result = dict(event="key_up", tick=tick, target_tick=event["target_tick"], lane=event["lane"],
                      key=event["key"], game_mask=event["mask"], reason=reason, posted=posted,
                      attempts=attempted)
        if error and not posted: result["error"] = error
        return [result]

    def _disable(self, reason, tick):
        events = self._release(reason, tick, RELEASE_ATTEMPTS)
        self.disabled = reason
        if self.active is not None:
            events.append(dict(event="key_release_failed", tick=tick, reason=reason,
                               key=self.active["key"], game_mask=self.active["mask"]))
        events.append(dict(event="driver_disabled", tick=tick, reason=reason))
        return events

    def poll(self, tick, game_mask, context_valid):
        if self.closed or self.disabled: return []
        if not context_valid: return self._disable("invalid_context", tick)
        if (isinstance(tick, bool) or not isinstance(tick, int) or tick < 0 or
                isinstance(game_mask, bool) or not isinstance(game_mask, int) or game_mask < 0):
            return self._disable("invalid_state", tick)
        if self.last_tick is None:
            self.last_tick = tick
            skipped = []
            while self.index < len(self.schedule) and self.schedule[self.index][0] <= tick:
                row = self.schedule[self.index]; self.index += 1
                skipped.append(dict(event="stale_event_skipped", tick=tick, target_tick=row[1],
                                    lane=row[2], reason="initial_baseline"))
            return skipped
        if tick < self.last_tick: return self._disable("tick_reset", tick)

        previous = self.last_tick
        self.last_tick = tick
        if self.active is not None:
            if tick - previous > MAX_TICK_GAP:
                if game_mask & self.active["mask"]:
                    events = self._release("game_mask_observed_after_tick_gap", tick, RELEASE_ATTEMPTS)
                    self.disabled = "tick_gap"
                    if self.active is not None:
                        events.append(dict(event="key_release_failed", tick=tick, reason="tick_gap",
                                           key=self.active["key"], game_mask=self.active["mask"]))
                    events.append(dict(event="driver_disabled", tick=tick, reason="tick_gap"))
                else:
                    events = self._disable("tick_gap", tick)
                while self.index < len(self.schedule) and self.schedule[self.index][0] <= tick:
                    row = self.schedule[self.index]; self.index += 1
                    events.append(dict(event="stale_event_skipped", tick=tick, target_tick=row[1],
                                       lane=row[2], reason="poll_gap"))
                return events
            if game_mask & self.active["mask"]:
                return self._release("game_mask_observed", tick)
            if tick != previous: self.hold_updates += 1
            if self.hold_updates >= MAX_HOLD_UPDATES:
                return self._release("hold_limit", tick)
            return []
        if tick == previous: return []

        due, skipped = [], []
        while self.index < len(self.schedule) and self.schedule[self.index][0] <= tick:
            row = self.schedule[self.index]; self.index += 1
            if row[0] <= previous:
                skipped.append(dict(event="stale_event_skipped", tick=tick, target_tick=row[1],
                                    lane=row[2], reason="missed_tick"))
            else: due.append(row)
        if not due: return skipped
        if tick - previous > MAX_TICK_GAP or len(due) != 1:
            reason = "poll_gap" if tick - previous > MAX_TICK_GAP else "multiple_due"
            skipped.extend(dict(event="stale_event_skipped", tick=tick, target_tick=row[1],
                                lane=row[2], reason=reason) for row in due)
            return skipped
        fire_tick, target, lane, key, vk, mask = due[0]
        try: posted = bool(self.backend.key(vk, True))
        except Exception: posted = False
        if not posted: return skipped + self._disable("key_down_failed", tick)
        self.active = dict(target_tick=target, lane=lane, key=key, vk=vk, mask=mask)
        self.hold_updates = 0
        skipped.append(dict(event="key_down", tick=tick, fire_tick=fire_tick, target_tick=target,
                            lane=lane, key=key, game_mask=mask, posted=True))
        return skipped

    def close(self):
        if self.closed and self.active is None: return []
        events = self._release("close", self.last_tick, RELEASE_ATTEMPTS)
        self.closed = True
        if self.active is not None:
            self.disabled = self.disabled or "close_release_failed"
            events.append(dict(event="key_release_failed", tick=self.last_tick, reason="close",
                               key=self.active["key"], game_mask=self.active["mask"]))
        return events
