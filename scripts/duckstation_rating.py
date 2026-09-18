"""Decode the visible U Rappin tier from a guarded gameplay state snapshot."""
import struct

_RATING_OFFSET = 0x4E
_RATING_NAMES = {
    0: "Cool",  # Best tier; inferred from the common ordered state machine.
    1: "Good",
    2: "Bad",
    3: "Awful",
}
COOL_PROMPT = "Cool. Freestyle, note cues off."


def rating_name(state, active=False):
    """Return a tier label only for an active stage snapshot, else None.

    ``state`` is the byte snapshot beginning at 0x801C3640. The caller owns
    stage/scene/retry guards and passes ``active=True`` only while that state
    is current gameplay.
    """
    if not active:
        return None
    try:
        view = memoryview(state)
        if view.nbytes < _RATING_OFFSET + 2:
            return None
        raw = struct.unpack_from("<h", view, _RATING_OFFSET)[0]
    except (TypeError, ValueError, struct.error):
        return None
    return _RATING_NAMES.get(raw)


def freestyle_active(state, active=False):
    """True while the visible tier is Cool.

    On Cool the teacher leaves and the player raps freely, so the note chart
    is not needed and its cues are muted.
    """
    return rating_name(state, active) == "Cool"


def rating_announcement(current, previous=None):
    """Spoken text for a tier, saying when the note cues turn off or back on."""
    if current == "Cool":
        return COOL_PROMPT
    if previous == "Cool":
        return f"{current}. Note cues on."
    return f"{current}."


class RatingChanges:
    """Baseline each active stage; announce actual tier changes only."""
    def __init__(self):
        self.stage = self.previous = self.changed_from = None

    def poll(self, state, stage=None, active=False):
        current = rating_name(state, active)
        self.changed_from = None
        if current is None or stage is None:
            self.stage = self.previous = None
            return None
        changed = self.stage == stage and self.previous is not None and current != self.previous
        if changed:
            self.changed_from = self.previous
        self.stage, self.previous = stage, current
        return current if changed else None
