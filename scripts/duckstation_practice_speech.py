"""Pure Practice-screen speech for an externally guarded DuckStation state."""


STATE_SIZE = 0xB0
_PANEL_FLAG = 0x400000
_FEEDBACK_OFFSET = 0x1C

_FEEDBACK = {
    0: "Exactly!",
    1: "You are too quick.",
    2: "You are too slow.",
    4: "Next one is ...",
    5: "How about this one?",
    6: "The last one is ...",
    7: "OK, are you ready? Let's go rappin!",
    8: "You wanna try again?",
}

_INITIAL_HINT = "Look at the bar, press the Triangle button. X Exit."
_FINAL_HINT = "Push the Circle button to try again. X Exit."


class PracticeSpeechReader:
    """Speak verified Practice-panel changes; the caller supplies active context."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        """Forget the active screen, last panel, and H-only hint."""
        self._active = False
        self._last_phase = None
        self._hint = ""

    def hint(self) -> str:
        """Return the current H-only controls without a spoken prefix."""
        return self._hint

    def poll(self, state: bytes, active: bool) -> list[str]:
        """Return speech for a newly entered screen or changed feedback panel.

        ``state`` must be the guarded 0xB0-byte scene-state snapshot. When the
        Practice panel flag is clear, its effective phase is blank (-1).
        """
        if type(active) is not bool or not active:
            self.reset()
            return []
        if not isinstance(state, (bytes, bytearray, memoryview)) or len(state) != STATE_SIZE:
            self.reset()
            return []

        flag = int.from_bytes(state[0:4], "little")
        phase = (
            int.from_bytes(state[_FEEDBACK_OFFSET:_FEEDBACK_OFFSET + 4], "little")
            if flag & _PANEL_FLAG
            else -1
        )

        speech = []
        if not self._active:
            speech.append("Practice.")

        if phase != self._last_phase:
            feedback = _FEEDBACK.get(phase)
            if feedback is not None:
                speech.append(feedback)
                self._hint = _FINAL_HINT if phase == 8 else _INITIAL_HINT
            elif phase == -1:
                self._hint = _INITIAL_HINT
            else:
                self._hint = ""

        self._active = True
        self._last_phase = phase
        return speech


__all__ = ["PracticeSpeechReader"]
