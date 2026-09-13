"""Read-only RAM adapter for verified PaRappa menu and card UI fields.

The adapter consumes a ``ram.read(address, size) -> bytes`` object such as
``duckstation_memory.ReadOnlyRAM``. It never changes game state. Title choice
is available only when the caller explicitly leases the verified live stack
word captured at PC ``0x801c4d24``. The lease is discarded if the title code
signature changes or a main-menu entry ends the title context.
"""

from __future__ import annotations

import struct
import time
from typing import Callable


MAIN_STATE = 0x800544F8
MAIN_DESCRIPTOR = 0x80054550
MAIN_DRAW = 0x80026720

LANGUAGE_STATE = 0x8005451C
LANGUAGE_DESCRIPTOR = 0x800545A0

STAGE_DESCRIPTOR = 0x8005453C
STAGE_STATE = 0x80087B78
STAGE_INIT = 0x800267F8
STAGE_DRAW = 0x80026170

CARD_MODE_DISPATCH = 0x800180D8
CARD_MODE_DISPATCH_WORD = 0x27BDFFE0
MAPPED_RESOURCE_KEY = 0x8006ED00
CARD_OBJECT_POINTER = 0x8006EAC4
NAME_STATE = 0x80049244
NAME_KEYBOARD = 0x800490E8
NAME_RESOURCE_KEY = 5
NAME_HINT_EDIT = "D-pad Select. X Type. Triangle Delete. Select End to finish."
NAME_HINT_END = "X Save. Circle Cancel."

HIGHSCORE_STATE = 0x80049278
HIGHSCORE_RECORDS = 0x8009421C

MAIN_IDLE_SECONDS = 2.25
TITLE_GUARD_ADDRESS = 0x801C4D20
TITLE_GUARD_WORDS = (0x8FA50010, 0x0C071615)
TITLE_DESCRIPTION = (
    "PaRappa beneath a colorful logo. PaRappa the Rapper, trademark. "
    "The Hip Hop Hero. "
    "Copyright 1997 Sony Computer Entertainment Inc. Copyright Rodney A. Greenblat slash Interlink. "
    "Trademark of Sony Computer Entertainment America Inc. "
)
TITLE_HINT = "D-pad Left and Right Select. X Confirm."

MAIN_ITEMS = (
    "Language.",
    "High scores.",
    "Difficulty.",
    "Stage.",
    "Exit.",
)
MAIN_HINTS = (
    "X Open.",
    "X Open.",
    "X Normal. Circle Easy.",
    "X Stage. Square Practice. Circle Replay. Triangle Load.",
    "X Exit.",
)
LANGUAGES = ("English", "Deutsch", "Fran\u00e7ais", "Italiano", "Espa\u00f1ol")
RANKS = ("Gold", "Silver", "Bronze")
STAGE_HINTS = {
    "play": "D-pad Select. X Play.",
    "exit": "D-pad Select. X Exit.",
}

_PUNCTUATION = {
    45: "Dash",
    33: "Exclamation mark",
    64: "At sign",
    35: "Number sign",
    36: "Dollar sign",
    38: "Ampersand",
    8: "Delete",
    10: "End. Cancel",
    37: "Smiling face",
    94: "Laughing face",
    61: "Target",
    123: "Asterisk",
    40: "Crescent moon",
    41: "Fish skeleton",
    95: "Lightning bolt",
    43: "Heart",
    44: "Sun",
    46: "Curved symbol",
    125: "Boxed X",
    91: "Music notes",
    93: "Star",
}


def _word(data: bytes, offset: int = 0) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _u16(data: bytes, offset: int = 0) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _s16(data: bytes, offset: int = 0) -> int:
    return struct.unpack_from("<h", data, offset)[0]


def _letter(code: int) -> str:
    if code in _PUNCTUATION:
        return _PUNCTUATION[code]
    if 48 <= code <= 57 or 65 <= code <= 90:
        return chr(code)
    return f"Symbol {code}"


def _display_name(value: str) -> str:
    if all("A" <= char <= "Z" or "0" <= char <= "9" for char in value):
        return value
    return " ".join(_letter(ord(char)) for char in value)


def _ascii_text(data: bytes) -> str:
    chars = []
    for byte in data:
        if byte == 0:
            break
        if 32 <= byte <= 126:
            chars.append(chr(byte))
    return "".join(chars)


class MenuReader:
    """Speak state transitions from validated menu RAM shapes only.

    ``poll`` returns zero or one speech string. The current H-only controls
    string is available from ``hint`` and is never returned by ``poll``.
    Call ``poll`` before ``hint``. The caller should invoke ``reset`` when it
    discards a RAM session or otherwise knows that a prior screen has closed.

    Main-menu activity is gated by the observed toggling halfword at
    ``0x800544f8`` plus changed selection state, so stale menu objects from a
    previously visited screen do not announce during a static RAM poll. A
    recognized High Scores screen also requires a pending High Scores choice
    from the active main menu. Title selection is read only through an
    explicitly leased stack address supplied by the caller; the title code
    signature is checked on every poll, and the lease ends at main-menu entry.
    Stage Select requires a pending Stage choice from the active Main menu and
    a changed, guarded Stage state shape. This prevents a stale Stage object
    from being announced while the user is still on Main. Name entry requires
    an observed transition to mapped resource key 5, the verified Name object
    pointer, the dispatcher signature, and its guarded keyboard state. An
    unchanged first-seen cache value never activates it. Redux's CPU breakpoint
    reader can distinguish card mode arguments, but DuckStation's RAM-only
    observer cannot. The Save? cache key is shared by another card mode and can
    remain cached after the prompt closes; the saved-slot mode is also transient
    CPU state. Save?, Save, Load, and Replay screens therefore stay silent until
    active-state guards are available.
    """

    def __init__(
        self,
        ram,
        clock: Callable[[], float] | None = None,
        title_selector_address: int | None = None,
    ):
        self.ram = ram
        self._clock = clock or time.monotonic
        self._main_candidate = None
        self._main_active = False
        self._main_phase = None
        self._main_last_activity = None
        self._main_key = None
        self._pending = None
        self._screen = None
        self._hint = ""
        self._language_key = None
        self._stage_baseline = None
        self._stage_key = None
        self._name_last_mapped = None
        self._name_pending = False
        self._name_active = False
        self._name_cursor = None
        self._name_code = None
        self._name_value = None
        self._title_selector_address = None
        self._title_selection = None
        if title_selector_address is not None:
            self.set_title_context(title_selector_address)

    @staticmethod
    def _valid_title_selector_address(address) -> bool:
        return (
            isinstance(address, int)
            and 0x80000000 <= address <= 0x801FFFFC
            and address % 4 == 0
        )

    def _invalidate_title_lease(self) -> None:
        self._title_selector_address = None
        self._title_selection = None
        if self._screen == "title":
            self._screen = None
            self._hint = ""

    def set_title_context(self, address: int) -> bool:
        """Explicitly lease a fresh stack word captured on the title screen.

        The address is the RAM address of ``SP+0x10`` captured by the caller
        while PC ``0x801c4d24`` was guarded, or reconstructed from the verified
        live title/VSync call chain. Arbitrary later SP values are not valid
        context. A rejected address clears any prior lease.
        """
        if not self._valid_title_selector_address(address):
            self._invalidate_title_lease()
            return False
        self._title_selector_address = address
        self._title_selection = None
        if self._screen == "title":
            self._screen = None
            self._hint = ""
        return True

    def _title_guard_valid(self) -> bool:
        if self._title_selector_address is None:
            return False
        code = self._read(TITLE_GUARD_ADDRESS, 8)
        if (_word(code), _word(code, 4)) != TITLE_GUARD_WORDS:
            self._invalidate_title_lease()
            return False
        return True

    def _title_suppressed(self) -> bool:
        return (
            self._main_active
            or self._screen in ("main", "language", "highscores", "name")
            or self._pending in ("language", "highscores")
        )

    def _clear_name_state(self) -> None:
        self._name_pending = False
        self._name_active = False
        self._name_cursor = None
        self._name_code = None
        self._name_value = None
        if self._screen == "name":
            self._screen = None
            self._hint = ""

    def _reset_name_gate(self) -> None:
        """Forget Name activity and baseline against the currently cached key."""
        self._clear_name_state()
        self._name_last_mapped = _word(self._read(MAPPED_RESOURCE_KEY, 4))

    def _name_observation(self):
        if (
            _word(self._read(CARD_MODE_DISPATCH, 4)) != CARD_MODE_DISPATCH_WORD
            or _word(self._read(CARD_OBJECT_POINTER, 4)) != NAME_STATE
        ):
            return None
        state = self._read(NAME_STATE, 0x22)
        if _word(state, 0x0C) != NAME_KEYBOARD:
            return None
        count = _s16(state, 0x14)
        cursor = _s16(state, 0x16)
        length = _s16(state, 0x18)
        if count != 57 or not 0 <= cursor < count or not 0 <= length <= 6:
            return None
        keyboard = self._read(NAME_KEYBOARD, count)
        return {
            "cursor": cursor,
            "code": keyboard[cursor],
            "name": _ascii_text(state[0x1C:0x22]),
        }

    @staticmethod
    def _name_hint(code: int) -> str:
        return NAME_HINT_END if code == 10 else NAME_HINT_EDIT

    def _poll_name(self, *, allow_activation: bool) -> list[str]:
        mapped = _word(self._read(MAPPED_RESOURCE_KEY, 4))
        previous = self._name_last_mapped
        self._name_last_mapped = mapped
        if previous is None:
            # Establish a baseline only. A persisted 5 is not evidence of a
            # live Name screen when monitoring starts or resets.
            return []
        if mapped != NAME_RESOURCE_KEY:
            if self._name_active or self._name_pending:
                self._clear_name_state()
            return []
        if mapped != previous:
            # The edge is necessary but not sufficient; wait for the object,
            # dispatcher and keyboard shape to become valid before speaking.
            self._clear_name_state()
            self._name_pending = True
        if not self._name_pending and not self._name_active:
            return []

        observation = self._name_observation()
        if observation is None:
            # A pending edge may precede state initialization. Once active,
            # loss of any guard ends the H hint and cannot re-arm without a
            # later mapped-key transition.
            if self._name_active:
                self._clear_name_state()
            return []

        if not self._name_active:
            if not allow_activation:
                return []
            if (
                self._pending in ("language", "highscores", "stage")
                or self._screen in ("language", "highscores", "stage")
            ):
                return []
            self._name_pending = False
            self._name_active = True
            self._name_cursor = observation["cursor"]
            self._name_code = observation["code"]
            self._name_value = observation["name"]
            self._screen = "name"
            self._hint = self._name_hint(observation["code"])
            return [
                "Name entry. Enter your name here. "
                + _letter(observation["code"])
                + "."
            ]

        cursor = observation["cursor"]
        code = observation["code"]
        name = observation["name"]
        self._hint = self._name_hint(code)
        if cursor != self._name_cursor:
            self._name_cursor = cursor
            self._name_code = code
            self._name_value = name
            return [_letter(code) + "."]
        if name != self._name_value:
            self._name_code = code
            self._name_value = name
            value = "blank" if not name else _display_name(name)
            return ["Name " + value + "."]
        self._name_code = code
        return []

    def _poll_title(self) -> list[str]:
        if self._title_selector_address is None or self._title_suppressed():
            return []
        if not self._title_guard_valid():
            return []
        selected = _word(self._read(self._title_selector_address, 4))
        if selected not in (0, 1) or selected == self._title_selection:
            return []
        entering = self._title_selection is None
        self._title_selection = selected
        self._screen = "title"
        self._hint = TITLE_HINT
        item = "Start." if selected == 0 else "Menu."
        return [(TITLE_DESCRIPTION if entering else "") + item]

    def _read(self, address: int, size: int) -> bytes:
        data = self.ram.read(address, size)
        if not isinstance(data, bytes) or len(data) != size:
            raise ValueError("RAM reader returned a short or non-byte result")
        return data

    def _main_observation(self):
        descriptor = self._read(MAIN_DESCRIPTOR, 0x14)
        if (
            _word(descriptor, 0x00) != 0x80026794
            or _word(descriptor, 0x04) != 0x800264AC
            or _word(descriptor, 0x08) != MAIN_DRAW
            or _word(descriptor, 0x0C) != 0
            or _word(descriptor, 0x10) != MAIN_STATE
            or _word(self._read(MAIN_DRAW, 4)) != 0x27BDFFE8
        ):
            return None

        state = self._read(MAIN_STATE, 0x1C)
        selected = _u16(state, 0x0C)
        count = _u16(state, 0x0E)
        difficulty = _u16(state, 0x18)
        app_mode = _u16(self._read(0x800916D0, 2))
        if app_mode != 0 or count != 5 or selected > 4 or difficulty > 1:
            return None
        return {
            "phase": _u16(state, 0),
            "selected": selected,
            "difficulty": difficulty,
        }

    @staticmethod
    def _pending_for(selected: int) -> str | None:
        if selected == 0:
            return "language"
        if selected == 1:
            return "highscores"
        if selected == 3:
            return "stage"
        return None

    @staticmethod
    def _main_label(selected: int, difficulty: int, include_item: bool) -> str:
        if selected == 2:
            value = "Normal." if difficulty == 0 else "Easy."
            return ("Difficulty. " if include_item else "") + value
        return MAIN_ITEMS[selected]

    def _set_main_item(self, selected: int, difficulty: int, entering: bool) -> str | None:
        key = (selected, difficulty)
        previous = self._main_key
        if previous == key and not entering:
            return None
        # The title stack slot ceases to describe a live title selector once
        # the main menu is confirmed. Require a fresh caller lease on any
        # later title context instead of trusting a reused stack address.
        self._invalidate_title_lease()
        self._reset_name_gate()
        if entering:
            text = "Main menu. " + self._main_label(selected, difficulty, True)
        elif previous and selected == previous[0] == 2 and difficulty != previous[1]:
            text = "Easy." if difficulty else "Normal."
        else:
            text = self._main_label(selected, difficulty, True)
        self._main_key = key
        self._pending = self._pending_for(selected)
        if self._pending == "stage":
            # Remember the already-loaded state before Stage is opened. A
            # later guarded state transition is required before it can speak.
            self._stage_baseline = self._stage_observation()
        else:
            self._stage_baseline = None
        self._stage_key = None
        self._screen = "main"
        self._hint = MAIN_HINTS[selected]
        return text

    def _update_main(self, observation, now: float) -> list[str]:
        if observation is None:
            self._main_candidate = None
            self._main_active = False
            self._main_phase = None
            self._main_last_activity = None
            if self._screen == "main":
                self._screen = None
                self._hint = ""
            return []

        if self._main_candidate is None:
            self._main_candidate = observation
            self._main_phase = observation["phase"]
            return []

        previous_candidate = self._main_candidate
        self._main_candidate = observation
        phase_changed = observation["phase"] != previous_candidate["phase"]
        item_changed = (observation["selected"], observation["difficulty"]) != (
            previous_candidate["selected"], previous_candidate["difficulty"]
        )

        if self._main_active:
            if phase_changed or item_changed:
                self._main_last_activity = now
            self._main_phase = observation["phase"]
            if (
                self._main_last_activity is not None
                and now - self._main_last_activity > MAIN_IDLE_SECONDS
            ):
                self._main_active = False
                if self._screen == "main":
                    self._screen = None
                    self._hint = ""
                return []
            if item_changed:
                message = self._set_main_item(
                    observation["selected"], observation["difficulty"], False
                )
                return [message] if message else []
            return []

        # The observed phase toggles while the main menu is drawn. Selection
        # changes are also activity, and are useful when polling misses a phase.
        if phase_changed or item_changed:
            self._main_active = True
            self._main_phase = observation["phase"]
            self._main_last_activity = now
            message = self._set_main_item(
                observation["selected"], observation["difficulty"], True
            )
            return [message] if message else []
        return []

    def _language_observation(self):
        descriptor = self._read(LANGUAGE_DESCRIPTOR, 0x14)
        if (
            _word(descriptor, 0x00) != 0x800268E4
            or _word(descriptor, 0x04) != 0x80026910
            or _word(descriptor, 0x08) != 0x80026B54
            or _word(descriptor, 0x10) != LANGUAGE_STATE
            or _word(self._read(0x80026B54, 8)) != 0x27BDFFE8
            or _word(self._read(0x80026B58, 4)) != 0xAFBF0010
            or _u16(self._read(0x800916D0, 2)) != 0
        ):
            return None
        state = self._read(LANGUAGE_STATE, 0x18)
        group, group_count = _s16(state, 8), _s16(state, 10)
        subtitle, subtitle_count = _s16(state, 12), _s16(state, 14)
        language, language_count = _s16(state, 16), _s16(state, 18)
        exit_item, exit_count = _s16(state, 20), _s16(state, 22)
        if (
            (group, group_count) not in ((0, 3), (1, 3), (2, 3))
            or (subtitle, subtitle_count) not in ((0, 2), (1, 2))
            or not 0 <= language < 5
            or language_count != 5
            or exit_item != 0
            or exit_count != 1
        ):
            return None
        return group, subtitle, language

    @staticmethod
    def _language_item(observation, entering: bool, previous_group: int | None):
        group, subtitle, language = observation
        value = (
            ("On." if subtitle == 0 else "Off.")
            if group == 0
            else LANGUAGES[language] + "."
            if group == 1
            else "Exit."
        )
        if entering:
            text = "Language. " + (("Subtitles. " if group == 0 else "") + value)
        elif group != previous_group and group == 0:
            text = "Subtitles. " + value
        else:
            text = value
        hint = (
            "X On. Circle Off. D-pad Up/Down Section."
            if group == 0
            else "Left/Right Select. Up/Down Section."
            if group == 1
            else "X Exit. D-pad Up/Down Section."
        )
        return text, hint

    def _read_highscores(self):
        table = self._read(HIGHSCORE_STATE, 0x10)
        rows, columns = _s16(table, 0x0C), _s16(table, 0x0E)
        if rows != 6 or columns != 3:
            return None
        records = self._read(HIGHSCORE_RECORDS, 6 * 0x40)
        parts = ["High scores."]
        for row in range(rows):
            entries = []
            for rank in range(columns):
                offset = row * 0x40 + rank * 0x10
                score = struct.unpack_from("<i", records, offset + 0x0C)[0]
                if score < 0:
                    return None
                name = _ascii_text(records[offset : offset + 3])
                if score > 0:
                    entries.append(
                        RANKS[rank]
                        + " "
                        + str(score)
                        + (" " + _display_name(name) if name else "")
                    )
                else:
                    entries.append(RANKS[rank] + " empty")
            parts.append(f"Stage {row + 1}. " + ". ".join(entries) + ".")
        parts.append("Exit.")
        return " ".join(parts)

    def _stage_observation(self):
        """Read the verified Stage Select descriptor and cursor shape."""
        if (
            _word(self._read(STAGE_INIT, 4)) != 0x8C860010
            or _word(self._read(STAGE_DRAW, 4)) != 0x27BDFFE8
            or _word(self._read(STAGE_DRAW + 8, 4)) != 0x8C840010
            or _word(self._read(STAGE_DESCRIPTOR + 0x10, 4)) != STAGE_STATE
        ):
            return None
        state = self._read(STAGE_STATE, 0x20)
        selected = _s16(state, 8)
        count = _s16(state, 0x0A)
        closed = _s16(state, 4)
        if count != 8 or not 1 <= selected <= 8 or closed not in (0, 1):
            return None
        words = tuple(_u16(state, offset) for offset in range(0, 0x20, 2))
        return {
            "selected": selected,
            "closed": closed,
            "availability": tuple(
                _u16(state, offset) for offset in range(0x0E, 0x1A, 2)
            ),
            "signature": words,
        }

    @staticmethod
    def _stage_label(selected: int) -> str:
        if selected == 8:
            return "Exit."
        if selected == 7:
            # The native cursor index is verified; its artwork/title is not.
            return "Selection 7."
        return f"Stage {selected}."

    def _clear_stage(self) -> None:
        self._stage_key = None
        self._stage_baseline = None
        self._pending = None
        if self._screen == "stage":
            self._screen = None
            self._hint = ""

    def _poll_stage(self) -> list[str]:
        observation = self._stage_observation()
        if self._screen == "stage":
            # The close word is set when Stage Select accepts Exit. Overlay or
            # descriptor loss also ends this RAM-only lease, clearing H hints.
            if observation is None or observation["closed"]:
                self._clear_stage()
                return []
            selected = observation["selected"]
            if selected == self._stage_key:
                return []
            self._stage_key = selected
            self._hint = STAGE_HINTS["exit" if selected == 8 else "play"]
            return [self._stage_label(selected)]

        if self._pending != "stage" or observation is None or observation["closed"]:
            return []
        baseline = self._stage_baseline
        if baseline is not None and observation["signature"] == baseline["signature"]:
            return []

        selected = observation["selected"]
        self._stage_key = selected
        self._stage_baseline = None
        self._pending = None
        self._reset_name_gate()
        self._screen = "stage"
        self._hint = STAGE_HINTS["exit" if selected == 8 else "play"]
        return ["Stage select."]

    def _poll_pending_screen(self, now: float) -> list[str]:
        if self._main_active:
            return []
        if (
            self._main_last_activity is not None
            and now - self._main_last_activity < MAIN_IDLE_SECONDS
        ):
            return []

        if self._pending == "language":
            observation = self._language_observation()
            if observation is None:
                return []
            entering = self._screen != "language"
            text, hint = self._language_item(
                observation,
                entering,
                self._language_key[0] if self._language_key else None,
            )
            if entering or observation != self._language_key:
                if entering:
                    self._reset_name_gate()
                self._screen = "language"
                self._language_key = observation
                self._hint = hint
                return [text]
            return []

        # Selecting High scores precedes card loading. The table may still
        # contain old/empty records here; the live modal guard in the monitor
        # announces it only when the game actually displays it.
        if self._pending == "stage" or self._screen == "stage":
            return self._poll_stage()
        return []

    def poll(self) -> list[str]:
        """Return speech for a newly observed, verified UI transition."""
        now = self._clock()
        try:
            # Keep the lease tied to the title overlay even when another
            # recognized menu causes an early return below.
            title_guard_valid = self._title_guard_valid()
            main = self._main_observation()
            events = self._update_main(main, now)
            if events:
                self._language_key = None
                return events

            name_events = self._poll_name(allow_activation=not self._main_active)
            if name_events:
                return name_events

            if self._main_active:
                return []

            events = self._poll_pending_screen(now)
            if events:
                self._language_key = (
                    self._language_key
                    if self._screen == "language"
                    else None
                )
                return events

            return self._poll_title() if title_guard_valid else []
        except (OSError, ValueError, struct.error):
            # A partial read or process shutdown must never produce speech.
            self.reset()
            return []

    def hint(self) -> str:
        """Return current H-only controls without adding a spoken prefix."""
        return self._hint

    def reset(self, *, baseline_name: bool = False) -> None:
        """Forget prior screen transitions after a caller-known context change."""
        self._main_candidate = None
        self._main_active = False
        self._main_phase = None
        self._main_last_activity = None
        self._main_key = None
        self._pending = None
        self._screen = None
        self._hint = ""
        self._language_key = None
        self._stage_baseline = None
        self._stage_key = None
        self._name_last_mapped = None
        self._name_pending = False
        self._name_active = False
        self._name_cursor = None
        self._name_code = None
        self._name_value = None
        self._title_selector_address = None
        self._title_selection = None
        if baseline_name:
            self._reset_name_gate()


__all__ = ["MenuReader"]
