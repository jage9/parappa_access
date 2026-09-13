"""Pinned Stage 1–6 cursor metadata and a read-only post-loop decoder.

Addresses are for the verified US SCUS-94183 overlays. ``passive_verified`` tracks the RAM-transition
shadow check specifically; exact read-breakpoint evidence is recorded
separately and must not be treated as a shadow pass.
"""
from __future__ import annotations

import struct
from typing import Mapping


DISC_SERIAL = "SCUS-94183"
DISC_IMG_SHA256 = "3f7d330bb10e2e3ae6c1f8a16239060fc137cab2cb384d12ccdb7bbebbe285c6"
PCSX_REDUX_VERSION = "25333.20260910.4.x64"
PCSX_REDUX_EXE_SHA256 = "cdd1806391cf39d6b696c4c6285ee6e22e0524d40679b8f82f4a928157ab937f"
PCSX_REDUX_MAIN_SHA256 = "38d599de46e6db075ab5ea5fa516bcadb9dc34f60a5fefadafe13076ce12caa1"
OPENBIOS_SHA256 = "713ea2aed58606282b3ff5e91d77f8c5892ea36f5adcd279d2c7dd26604a625d"
SCENE_STATE = 0x801C3640
SCENE_GRID_POINTER = 0x800943D0
SCENE_GRID_COUNT = 0x800943D4
COMMON_STATE = 0x800916D0
COMMON_APP_MODE = 0
STATE_SIZE = 0xB0
GRID_RECORD_SIZE = 44
GRID_RECORD_START_OFFSETS = (4, 24)
CURSOR_FLAG_MASK = 0x00000008
INDEX_AFTER_CONSUME_MIN = 3
INDEX_AFTER_CONSUME_MAX = 19
LANES = {
    1: "TRIANGLE",
    2: "CIRCLE",
    3: "X",
    4: "SQUARE",
    5: "L1",
    6: "L1",
    7: "R1",
    8: "R1",
}


# The six exact reads share one scene-state layout across the pinned overlays.
# ``read_sites`` below binds the stage-specific breakpoints to these gates.
_CURSOR_FIELDS = (
    {
        "name": "primary_a",
        "stream": "PRIMARY",
        "pointer_offset": 0x94,
        "index_offset": 0x8C,
        "active_offset": 0x90,
        "allowed_gates": ((1, 1), (2, 1)),
    },
    {
        "name": "primary_b",
        "stream": "PRIMARY",
        "pointer_offset": 0x98,
        "index_offset": 0x8E,
        "active_offset": 0x90,
        "allowed_gates": ((2, 2),),
    },
    {
        "name": "response_a",
        "stream": "RESPONSE",
        "pointer_offset": 0xA4,
        "index_offset": 0x9E,
        "active_offset": 0xA2,
        "allowed_gates": ((1, 1), (2, 1)),
    },
    {
        "name": "response_b",
        "stream": "RESPONSE",
        "pointer_offset": 0xA8,
        "index_offset": 0xA0,
        "active_offset": 0xA2,
        "allowed_gates": ((2, 2),),
    },
)


def _read_sites(primary: tuple[int, ...], response: tuple[int, ...]) -> tuple[dict, ...]:
    specs = (
        (primary[0], "primary_a", 1, 1),
        (primary[1], "primary_a", 2, 1),
        (primary[2], "primary_b", 2, 2),
        (response[0], "response_a", 1, 1),
        (response[1], "response_a", 2, 1),
        (response[2], "response_b", 2, 2),
    )
    fields = {item["name"]: item for item in _CURSOR_FIELDS}
    return tuple(
        {
            "address": address,
            "cursor": cursor,
            "stream": fields[cursor]["stream"],
            "pointer_offset": fields[cursor]["pointer_offset"],
            "index_offset": fields[cursor]["index_offset"],
            "active_offset": fields[cursor]["active_offset"],
            "mode": mode,
            "active": active,
            "flag_mask": CURSOR_FLAG_MASK,
        }
        for address, cursor, mode, active in specs
    )


def _profile(
    stage: int,
    teacher: str,
    entry: int,
    loop: int,
    result: int,
    grid: int,
    count: int,
    primary: tuple[int, ...],
    response: tuple[int, ...],
    *,
    loop_word: int = 0x27BDFFD0,
    result_word: int = 0x3C128009,
    overlay: str | None = None,
    overlay_sha256: str | None = None,
    exact_gate_evidence: str,
    passive_verified: bool = False,
    passive_evidence: str | None = None,
    allow_initial_index1_to2: bool = False,
    allow_initial_secondary_minus1_to3: bool = False,
) -> dict:
    context = {
        "scene_state": SCENE_STATE,
        "entry_word": 0x27BDFFC8,
        "loop_word": loop_word,
        "grid": grid,
        "grid_count": count,
        "app_mode": COMMON_APP_MODE,
    }
    return {
        "stage": stage,
        "teacher": teacher,
        "disc_serial": DISC_SERIAL,
        "disc_img_sha256": DISC_IMG_SHA256,
        "emulator_version": PCSX_REDUX_VERSION,
        "emulator_exe_sha256": PCSX_REDUX_EXE_SHA256,
        "emulator_main_sha256": PCSX_REDUX_MAIN_SHA256,
        "bios_sha256": OPENBIOS_SHA256,
        "overlay": overlay,
        "overlay_sha256": overlay_sha256,
        "entry": entry,
        "entry_word": 0x27BDFFC8,
        "loop": loop,
        "loop_word": loop_word,
        "result": result,
        "result_word": result_word,
        "grid": grid,
        "count": count,
        "grid_record_size": GRID_RECORD_SIZE,
        "state_address": SCENE_STATE,
        "state_size": STATE_SIZE,
        "grid_pointer_address": SCENE_GRID_POINTER,
        "grid_count_address": SCENE_GRID_COUNT,
        "common_state_address": COMMON_STATE,
        "context_expected": context,
        "primary": primary,
        "response": response,
        "cursor_fields": _CURSOR_FIELDS,
        "read_sites": _read_sites(primary, response),
        "gate_flag_mask": CURSOR_FLAG_MASK,
        "grid_record_start_offsets": GRID_RECORD_START_OFFSETS,
        "index_after_consume": (INDEX_AFTER_CONSUME_MIN, INDEX_AFTER_CONSUME_MAX),
        "allow_initial_index1_to2": allow_initial_index1_to2,
        "allow_initial_secondary_minus1_to3": allow_initial_secondary_minus1_to3,
        "exact_gate_runtime_evidence": exact_gate_evidence,
        "passive_verified": passive_verified,
        "passive_validation": "pass" if passive_verified else "pending_full_shadow",
        "passive_evidence": passive_evidence,
        # A later-stage exact-read check does not validate the new post-loop
        # decoder. Keep later cue emission disabled until that shadow passes.
        "cue_emission_enabled": passive_verified,
    }


# Stage 3/4/6 exact reads and passive shadows show a valid first note can be
# read at index 1, followed by a same-pointer 1->2 RAM transition. Stage 5/6
# exact reads and full diagnostics also show an initial secondary-cursor read
# at index 2, followed by a same-pointer -1->3 transition. Keep both rules
# profile-scoped; enable cues only with a completed passive-shadow pass below.
PROFILES = {
    1: _profile(
        1, "Master Onion", 0x801C7A60, 0x801C81EC, 0x801C82F8,
        0x801CFA54, 36,
        (0x801C9258, 0x801C92B4, 0x801C9310),
        (0x801C9398, 0x801C93F4, 0x801C9450),
        overlay="S1_COMOD1.BIN;1",
        overlay_sha256="d329767bc22287df56d56c45ee5b92bb495717465d48997e88c9939025192932",
        exact_gate_evidence="Stage 1 exact-read BPs and full passive shadow",
        passive_verified=True,
        passive_evidence="logs/cursor-shadow-full-20260912.log: 53/53 primary and response matches; all ticks equal",
    ),
    2: _profile(
        2, "Instructor Mooselini", 0x801C6D58, 0x801C74E4, 0x801C75F0,
        0x801CDAE0, 38,
        (0x801C88D0, 0x801C892C, 0x801C8988),
        (0x801C8A10, 0x801C8A6C, 0x801C8AC8),
        overlay="S2_COMOD2.BIN;1",
        overlay_sha256="c1e3725bcc563b520ed2e21962c9065946cfd98b4dac70c82a5e39e86f8d06d3",
        exact_gate_evidence="logs/stage2-confirm-cursors.log: strict exact-read gate and lane checks",
        passive_verified=True,
        passive_evidence="logs/passive-stage2-full-20260912.log: 88/88 primary and response matches; all ticks equal; clear",
    ),
    3: _profile(
        3, "Prince Fleaswallow", 0x801C70F4, 0x801C7880, 0x801C798C,
        0x801D0E78, 24,
        (0x801C8AD4, 0x801C8B30, 0x801C8B8C),
        (0x801C8C14, 0x801C8C70, 0x801C8CCC),
        overlay="S3_COMOD3.BIN;1",
        overlay_sha256="76d0ca49fbc018e993a245b60a3c01929bd417c3025d3edcba1dde7dc2e6c65b",
        exact_gate_evidence="logs/play-stage3-developer.log: strict gate checks over primary and response streams",
        passive_verified=True,
        passive_evidence="logs/passive-stage3-corrected-20260912.log: 131/131 primary and response matches; all ticks equal; clear",
        allow_initial_index1_to2=True,
    ),
    4: _profile(
        4, "Cheap Cheap", 0x801C84FC, 0x801C8C88, 0x801C8D94,
        0x801D3244, 26,
        (0x801CA254, 0x801CA2B0, 0x801CA30C),
        (0x801CA394, 0x801CA3F0, 0x801CA44C),
        overlay="S5_COMOD5.BIN;1",
        overlay_sha256="035e5910214e589543476fa8b2c814115b2243934333caf5fc08034db9bb90cb",
        exact_gate_evidence="logs/play-stage4-developer.log: strict gate checks over primary and response streams",
        passive_verified=True,
        passive_evidence="logs/passive-stage4-corrected-20260912.log: 125/125 primary and response matches; all ticks equal; clear",
        allow_initial_index1_to2=True,
    ),
    5: _profile(
        5, "Teachers", 0x801C6894, 0x801C7030, 0x801C713C,
        0x801CFA9C, 21,
        (0x801C8468, 0x801C84C4, 0x801C8520),
        (0x801C85A8, 0x801C8604, 0x801C8660),
        result_word=0x00408021,
        overlay="S6_COMOD6.BIN;1",
        overlay_sha256="6b1921751a0db43486b5fbc837ff6a9e6de301afca81ef4726965fdbc90fa538",
        exact_gate_evidence="logs/play-stage5-developer.log: strict gate checks over primary and response streams",
        passive_verified=True,
        passive_evidence="logs/passive-stage5-corrected-resumed-20260912.log: 138/138 primary and response matches; all ticks equal; clear",
        allow_initial_secondary_minus1_to3=True,
    ),
    6: _profile(
        6, "MC King Kong Mushi", 0x801C72A0, 0x801C7A2C, 0x801C7B34,
        0x801D1D1C, 36,
        (0x801C8FD8, 0x801C9034, 0x801C9090),
        (0x801C9118, 0x801C9174, 0x801C91D0),
        loop_word=0x27BDFFD8,
        result_word=0x00408021,
        overlay="S7_COMOD7.BIN;1",
        overlay_sha256="1b4027af6edf2efbba077f7f75bda76c8fe6a3e7b2b4c58eeba07574d6ee6d4f",
        exact_gate_evidence="logs/play-stage6-fresh-132.log: strict gate checks across the completed developer run",
        passive_verified=True,
        passive_evidence="logs/passive-stage6-corrected-resumed-20260912.log: 112/112 primary and 132/132 response matches; all ticks equal; clear",
        allow_initial_index1_to2=True,
        allow_initial_secondary_minus1_to3=True,
    ),
}


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _s16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<h", data, offset)[0]


def validate_context(profile: Mapping, observed: Mapping[str, int]) -> dict:
    """Compare RAM observations to the profile's pinned context signatures.

    Required observation keys are ``scene_state``, ``entry_word``,
    ``loop_word``, ``grid``, ``grid_count`` and ``app_mode``. This check only
    establishes that the expected scene is active; it does not establish that
    the passive decoder has passed its shadow test.
    """
    expected = profile["context_expected"]
    mismatches = tuple(
        {
            "field": key,
            "expected": value,
            "observed": observed.get(key),
        }
        for key, value in expected.items()
        if observed.get(key) != value
    )
    return {
        "stage": profile["stage"],
        "valid": not mismatches,
        "mismatches": mismatches,
        "passive_verified": profile["passive_verified"],
        "cue_emission_enabled": profile["cue_emission_enabled"],
    }


def consumed_events(previous: bytes, current: bytes, grid: bytes, profile: Mapping) -> list[dict]:
    """Decode changed post-loop cursors from two read-only scene snapshots.

    Indices in the scene state are incremented after a byte is consumed. A
    candidate therefore uses ``current_index - 1`` to locate the byte. Only
    active, gated transitions inside the pinned grid are returned; no notes
    are extrapolated when observations are missed. Stage 3/4/6 profiles also
    accept the exact-evidenced same-pointer 1->2 initial-cell transition;
    Stage 5/6 accept their exact-evidenced secondary-cursor -1->3 transition.
    Other same-pointer index jumps are returned as rejected diagnostics.
    """
    if len(previous) < STATE_SIZE or len(current) < STATE_SIZE:
        raise ValueError(f"scene snapshots must each contain at least {STATE_SIZE:#x} bytes")
    grid_bytes = profile["count"] * GRID_RECORD_SIZE
    if len(grid) < grid_bytes:
        raise ValueError(f"grid snapshot must contain at least {grid_bytes} bytes")

    flags = _u32(current, 0)
    mode = _s16(current, 0x8A)
    tick = _u32(current, 0x0C)
    events = []
    for cursor in profile["cursor_fields"]:
        pointer_offset = cursor["pointer_offset"]
        index_offset = cursor["index_offset"]
        active_offset = cursor["active_offset"]
        pointer, index = _u32(current, pointer_offset), _s16(current, index_offset)
        old_pointer = _u32(previous, pointer_offset)
        old_index = _s16(previous, index_offset)
        if (pointer, index) == (old_pointer, old_index):
            continue
        if flags & CURSOR_FLAG_MASK != CURSOR_FLAG_MASK:
            continue
        active = _s16(current, active_offset)
        if (mode, active) not in cursor["allowed_gates"]:
            continue
        previous_mode = _s16(previous, 0x8A)
        previous_active = _s16(previous, active_offset)
        index1_to2 = (
            profile.get("allow_initial_index1_to2", False)
            and pointer == old_pointer
            and old_index == 1
            and index == 2
            and mode == previous_mode
            and active == previous_active
        )
        secondary_minus1_to3 = (
            profile.get("allow_initial_secondary_minus1_to3", False)
            and cursor["name"] in ("primary_b", "response_b")
            and pointer == old_pointer
            and old_index == -1
            and index == 3
            and mode == previous_mode == 2
            and previous_active == 1
            and active == 2
        )
        if (
            not INDEX_AFTER_CONSUME_MIN <= index <= INDEX_AFTER_CONSUME_MAX
            and not index1_to2
            and not secondary_minus1_to3
        ):
            continue

        base = profile["grid"]
        grid_offset = pointer - base
        if not 0 <= grid_offset < grid_bytes or grid_offset % GRID_RECORD_SIZE not in GRID_RECORD_START_OFFSETS:
            continue
        if pointer == old_pointer and index != old_index + 1 and not secondary_minus1_to3:
            events.append(
                {
                    "stage": profile["stage"],
                    "cursor": cursor["name"],
                    "stream": cursor["stream"],
                    "rejected": "index_jump",
                    "before": old_index,
                    "after": index,
                    "pointer": pointer,
                    "tick": tick,
                    "mode": mode,
                    "active": active,
                }
            )
            continue

        consumed_index = index - 1
        lane = grid[grid_offset + consumed_index]
        button = LANES.get(lane)
        if button is None:
            # Empty/terminator bytes are expected and are not note events.
            continue
        events.append(
            {
                "stage": profile["stage"],
                "cursor": cursor["name"],
                "stream": cursor["stream"],
                "button": button,
                "lane": lane,
                "pointer": pointer,
                "index": consumed_index,
                "post_index": index,
                "index_rule": "initial_1_to_2" if index1_to2 else
                    ("initial_secondary_minus1_to3" if secondary_minus1_to3 else "increment"),
                "tick": tick,
                "mode": mode,
                "active": active,
                "flags": flags,
            }
        )
    return events


__all__ = [
    "COMMON_APP_MODE",
    "COMMON_STATE",
    "CURSOR_FLAG_MASK",
    "DISC_SERIAL",
    "DISC_IMG_SHA256",
    "GRID_RECORD_SIZE",
    "LANES",
    "PROFILES",
    "PCSX_REDUX_VERSION",
    "SCENE_GRID_COUNT",
    "SCENE_GRID_POINTER",
    "SCENE_STATE",
    "STATE_SIZE",
    "consumed_events",
    "validate_context",
]
