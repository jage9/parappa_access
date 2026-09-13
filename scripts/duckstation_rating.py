"""Decode the visible U Rappin tier from a guarded gameplay state snapshot."""
import struct

_RATING_OFFSET = 0x4E
_RATING_NAMES = {
    0: "Cool",  # Best tier; inferred from the common ordered state machine.
    1: "Good",
    2: "Bad",
    3: "Awful",
}


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


class RatingChanges:
    """Baseline each active stage; announce actual tier changes only."""
    def __init__(self):
        self.stage = self.previous = None

    def poll(self, state, stage=None, active=False):
        current = rating_name(state, active)
        if current is None or stage is None:
            self.stage = self.previous = None
            return None
        changed = self.stage == stage and self.previous is not None and current != self.previous
        self.stage, self.previous = stage, current
        return current if changed else None
