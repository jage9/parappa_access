"""Decode title-card wait frames from DuckStation CPU snapshots.

Stage 1–6 and ending signatures were checked against natural scene samples
in the pinned DuckStation logs. These are screen signals, never rhythm cues.
"""

SCENE_TEXT = {
    1: "Stage 1. PaRappa portrait, pink lettering, Onion border. Card and subtitle: I need to become a hero!",
    2: "Stage 2. PaRappa portrait. You guys sit in the back.",
    3: "Stage 3. PaRappa portrait. My dad's gonna bite me!",
    4: "Stage 4. PaRappa portrait. Guaranteed to catch her heart.",
    5: "Stage 5. PaRappa portrait. Full tank.",
    6: "Stage 6. PaRappa portrait. I gotta believe!",
    7: "Ending scene.",
}

_WAIT_PCS = frozenset((0x800356D0, 0x8003571C))
_WAIT_GPRS = frozenset((0x8003561C, 0x800355F8))
_SCENE_POINTER = 0x801C3640
_STACK_BYTES = 0x70
_RAM_START = 0x80000000
_RAM_END = 0x80200000

# (card wait-call RA, intro caller RA). The wait RA is from the card routine's
# `jal 0x80035560`; the parent RA is saved by the card routine's own prologue.
_SCENE_WAIT_SIGNATURES = {
    1: (0x801C787C, 0x801C8278),
    2: (0x801C6B74, 0x801C7570),
    3: (0x801C6F10, 0x801C790C),
    4: (0x801C8318, 0x801C8D14),
    5: (0x801C66B0, 0x801C70BC),
    6: (0x801C70BC, 0x801C7AB4),
    # Key 7 identifies the Stage 6 ending, not another playable stage.
    7: (0x801C70BC, 0x801C7EB4),
}


def _u32(data, offset):
    return int.from_bytes(data[offset:offset + 4], "little")


def decode_scene_wait(pc, registers, stack):
    """Return a scene key for an exact card-loading wait frame.

    `registers` is the raw GPR block (GPR0..GPR31 as little-endian uint32s).
    `stack` is 0x70 or more bytes read from the current GPR29 stack address.
    The decoder is pure: it reads no emulator state and makes no timing guess.
    """
    if not isinstance(pc, int) or isinstance(pc, bool) or pc not in _WAIT_PCS:
        return None
    if not isinstance(registers, (bytes, bytearray, memoryview)) or len(registers) < 32 * 4:
        return None
    if not isinstance(stack, (bytes, bytearray, memoryview)) or len(stack) < _STACK_BYTES:
        return None

    sp = _u32(registers, 29 * 4)
    if sp & 3 or sp < _RAM_START or sp + _STACK_BYTES > _RAM_END:
        return None

    live_ra = _u32(registers, 31 * 4)
    saved_wait_ra = _u32(stack, 0x38)
    saved_card_ra = _u32(stack, 0x68)
    if _u32(stack, 0x18) != live_ra or live_ra not in _WAIT_GPRS:
        return None
    if _u32(stack, 0x30) != _SCENE_POINTER:
        return None

    for scene, (wait_ra, caller_ra) in _SCENE_WAIT_SIGNATURES.items():
        if saved_wait_ra == wait_ra and saved_card_ra == caller_ra:
            return scene
    return None
