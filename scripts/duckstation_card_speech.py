"""Read-only card-screen speech driven by an externally verified live context.

The caller supplies ``(mode, state_pointer)`` only while the guarded native
card-mode callback is active. This reader validates the dispatcher signature
and the known Name or slot-state shape before returning speech.
"""

from __future__ import annotations

import struct

from duckstation_menu import (
    CARD_MODE_DISPATCH,
    CARD_MODE_DISPATCH_WORD,
    NAME_HINT_EDIT,
    NAME_HINT_END,
    NAME_KEYBOARD,
    NAME_STATE,
    _ascii_text,
    _display_name,
    _letter,
    _s16,
    _word,
)


SLOT_STATE = 0x80048E50
SLOT_COUNT = 16
SLOT_NAME_TABLE = 0x8007A590
SLOT_RECORD_STRIDE = 0x6C
SLOT_NAME_OFFSET = 0x5C
HIGHSCORE_WAIT_MODE = 17
HIGHSCORE_WAIT_STATE = 0x8007CC50
HIGHSCORE_WAIT_TEXT = "Please wait a minute."
CARD_MESSAGES = {
    5: (HIGHSCORE_WAIT_STATE, "Insert Memory card! Exit.", "X Exit."),
    15: (NAME_STATE, "Now saving.", ""),
    16: (SLOT_STATE, "Don't remove memory card.", ""),
    HIGHSCORE_WAIT_MODE: (HIGHSCORE_WAIT_STATE, HIGHSCORE_WAIT_TEXT, ""),
}
CARD_MODES = {2, 10, 11, 12, 13, 22} | set(CARD_MESSAGES)
SLOT_HEADINGS = {11: "Save", 12: "Load", 13: "Replay"}
SLOT_ACTIONS = {11: "Save", 12: "Load", 13: "Replay"}


class DuckStationCardSpeechReader:
    """Report verified card-screen transitions from a read-only RAM adapter.

    ``poll`` accepts ``None`` when no card mode is active, or a two-item tuple
    containing the externally verified mode and its state pointer. It returns
    zero or one speech strings. The current H-only controls are returned by
    ``hint`` and never included in the speech result.
    """

    def __init__(self, ram):
        self.ram = ram
        self.reset()

    def _read(self, address: int, size: int) -> bytes:
        data = self.ram.read(address, size)
        if not isinstance(data, bytes) or len(data) != size:
            raise ValueError("RAM reader returned a short or non-byte result")
        return data

    def _dispatcher_valid(self) -> bool:
        return _word(self._read(CARD_MODE_DISPATCH, 4)) == CARD_MODE_DISPATCH_WORD

    def _name_observation(self, state_pointer: int):
        if state_pointer != NAME_STATE:
            return None
        state = self._read(NAME_STATE, 0x22)
        count = _s16(state, 0x14)
        cursor = _s16(state, 0x16)
        length = _s16(state, 0x18)
        if (
            _word(state, 0x0C) != NAME_KEYBOARD
            or count != 57
            or not 0 <= cursor < count
            or not 0 <= length <= 6
        ):
            return None
        keyboard = self._read(NAME_KEYBOARD, count)
        return {
            "cursor": cursor,
            "code": keyboard[cursor],
            "name": _ascii_text(state[0x1C:0x22]),
        }

    def _slot_observation(self, state_pointer: int, cursor_mode: int):
        if state_pointer != SLOT_STATE:
            return None
        state = self._read(SLOT_STATE, 0x16)
        count = _s16(state, 0x10)
        cursor = _s16(state, 0x14)
        if count != SLOT_COUNT or not 0 <= cursor < SLOT_COUNT:
            return None
        if cursor == SLOT_COUNT - 1:
            item = "Exit"
        else:
            address = SLOT_NAME_TABLE + cursor * SLOT_RECORD_STRIDE + SLOT_NAME_OFFSET
            name = _ascii_text(self._read(address, 6))
            item = _display_name(name) if name else f"Empty slot {cursor + 1}"
        action = "Exit" if cursor == SLOT_COUNT - 1 else SLOT_ACTIONS[cursor_mode]
        return {"cursor": cursor, "item": item, "action": action}

    def _clear_context(self) -> None:
        self._context = None
        self._last_item = None
        self._last_name = None
        self._hint = ""

    def reset(self) -> None:
        """Forget the active screen, cursor history, and H-only hint."""
        self._clear_context()

    def hint(self) -> str:
        """Return the current H-only controls without a spoken prefix."""
        return self._hint

    @staticmethod
    def _valid_context(context) -> bool:
        return (
            isinstance(context, tuple)
            and len(context) == 2
            and type(context[0]) is int
            and (context[1] is None or type(context[1]) is int)
            and context[0] in CARD_MODES
        )

    def poll(self, context: tuple[int, int | None] | None) -> list[str]:
        """Return speech for a newly observed, guarded card-screen change.

        Unverified modes are deliberately ignored. The high-score table remains
        on its separately verified path.
        """
        if context is None or not self._valid_context(context):
            self.reset()
            return []

        mode, state_pointer = context
        try:
            if not self._dispatcher_valid():
                self.reset()
                return []

            if mode in (2, 22):
                if mode == 22 and state_pointer != SLOT_STATE:
                    self.reset()
                    return []
                if context == self._context:
                    return []
                self._context = context
                self._last_item = None
                self._last_name = None
                self._hint = "X Yes. Circle No."
                return ["Save? Yes. No." if mode == 2 else "OK to overwrite? Yes. No."]

            if mode in CARD_MESSAGES:
                expected_state, text, hint = CARD_MESSAGES[mode]
                if state_pointer != expected_state:
                    self.reset()
                    return []
                if context == self._context:
                    return []
                self._context = context
                self._last_item = None
                self._last_name = None
                self._hint = hint
                return [text]

            if mode == 10:
                observation = self._name_observation(state_pointer)
                if observation is None:
                    self.reset()
                    return []
                cursor = observation["cursor"]
                code = observation["code"]
                name = observation["name"]
                hint = NAME_HINT_END if code == 10 else NAME_HINT_EDIT
                if context != self._context:
                    self._context = context
                    self._last_item = cursor
                    self._last_name = name
                    self._hint = hint
                    return ["Name entry. Enter your name here. " + _letter(code) + "."]

                speech = None
                if cursor != self._last_item:
                    speech = _letter(code) + "."
                elif name != self._last_name:
                    value = "blank" if name == "" else _display_name(name)
                    speech = "Name " + value + "."
                self._last_item = cursor
                self._last_name = name
                self._hint = hint
                return [speech] if speech else []

            if mode in SLOT_HEADINGS:
                observation = self._slot_observation(state_pointer, mode)
                if observation is None:
                    self.reset()
                    return []
                cursor = observation["cursor"]
                item = observation["item"]
                self._hint = (
                    "D-pad Select. X Exit."
                    if observation["action"] == "Exit"
                    else "D-pad Select. X " + observation["action"] + "."
                )
                if context != self._context:
                    self._context = context
                    self._last_item = cursor
                    self._last_name = None
                    return [SLOT_HEADINGS[mode] + ". " + item + "."]
                if cursor == self._last_item:
                    return []
                self._last_item = cursor
                return [item + "."]
        except (OSError, ValueError, struct.error):
            self.reset()
            return []

        self.reset()
        return []


__all__ = ["DuckStationCardSpeechReader"]
