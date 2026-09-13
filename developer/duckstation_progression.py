"""Stage-scoped wrapper for the opt-in DuckStation key driver."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from duckstation_developer import DeveloperController


STAGES = tuple(range(1, 7))

# The root CLI can load Stage 1 from its flat seed and Stages 2-6 from the
# stage-keyed Lua table. Counts are unique response target ticks.
SCHEDULE_METADATA = {
    "disc_serial": "SCUS-94183",
    "disc_img_sha256": "3f7d330bb10e2e3ae6c1f8a16239060fc137cab2cb384d12ccdb7bbebbe285c6",
    "tick_step": 24,
    "offset_ticks": -6,
    "source_files": {
        1: "logs/timing-stage1-seed.lua",
        2: "logs/passive-stage-seeds.lua",
        3: "logs/passive-stage-seeds.lua",
        4: "logs/passive-stage-seeds.lua",
        5: "logs/passive-stage-seeds.lua",
        6: "logs/passive-stage-seeds.lua",
    },
    "event_counts": {1: 53, 2: 88, 3: 131, 4: 125, 5: 138, 6: 132},
    "redux_version": "25333.20260910.4.x64",
    "redux_exe_sha256": "cdd1806391cf39d6b696c4c6285ee6e22e0524d40679b8f82f4a928157ab937f",
    "duckstation_exe_sha256": "2a74d36f9415af48751672e147c5e6ea9d606537aa8c6520b092d7afbc1bb592",
}


def validate_schedules(schedules: Mapping[int, Sequence[tuple[int, int]]]) -> dict[int, tuple[tuple[int, int], ...]]:
    """Copy and validate one nonempty, single-lane schedule for each stage."""
    if not isinstance(schedules, Mapping):
        raise TypeError("Schedules must be a stage-to-events mapping")
    if any(type(stage) is not int for stage in schedules):
        raise ValueError("Stage keys must be integer stages 1 through 6")
    if set(schedules) != set(STAGES):
        raise ValueError("Schedules must contain exactly stages 1 through 6")

    validated = {}
    for stage in STAGES:
        source = schedules[stage]
        if isinstance(source, (str, bytes)) or not isinstance(source, Sequence) or not source:
            raise ValueError(f"Stage {stage} schedule must be a nonempty event sequence")
        events = []
        for event in source:
            if isinstance(event, (str, bytes)) or not isinstance(event, Sequence) or len(event) != 2:
                raise ValueError(f"Stage {stage} events must be (tick, lane) pairs")
            tick, lane = event
            if type(tick) is not int or tick < 0:
                raise ValueError(f"Stage {stage} has an invalid target tick: {tick!r}")
            if tick % SCHEDULE_METADATA["tick_step"]:
                raise ValueError(f"Stage {stage} target tick is off the 24-tick grid: {tick}")
            if type(lane) is not int or lane not in range(1, 9):
                raise ValueError(f"Stage {stage} has an invalid lane: {lane!r}")
            events.append((tick, lane))

        expected_count = SCHEDULE_METADATA["event_counts"][stage]
        if len(events) != expected_count:
            raise ValueError(
                f"Stage {stage} needs {expected_count} seeded response events; found {len(events)}"
            )
        events.sort(key=lambda item: item[0])
        if any(events[index - 1][0] == events[index][0] for index in range(1, len(events))):
            raise ValueError(f"Stage {stage} has more than one lane at a target tick")
        validated[stage] = tuple(events)
    return validated


class MultiStageDeveloper:
    """Route active stage rounds to ordinary-input schedules, failing closed."""

    def __init__(self, pid, schedules, offset_ticks=-6, backend_factory=None):
        if type(offset_ticks) is not int or not -24 <= offset_ticks <= 24:
            raise ValueError("Offset must be an integer from -24 through 24 ticks")
        if backend_factory is not None and not callable(backend_factory):
            raise TypeError("backend_factory must be callable")
        self.pid = int(pid)
        self.schedules = validate_schedules(schedules)
        self.offset_ticks = offset_ticks
        self.backend_factory = backend_factory
        self._driver = None
        self._driver_stage = None
        self._stage = None
        self._closed = False

    @staticmethod
    def _annotate(events, stage):
        return [dict(event, stage=stage) for event in events]

    def _stop_round(self):
        if self._driver is None:
            return []
        old_stage = self._driver_stage
        events = self._annotate(self._driver.close(), old_stage)
        self._driver = None
        self._driver_stage = None
        return events

    def _start_round(self, stage):
        backend = self.backend_factory(self.pid) if self.backend_factory is not None else None
        self._driver = DeveloperController(
            self.pid,
            self.schedules[stage],
            self.offset_ticks,
            backend=backend,
        )
        self._driver_stage = stage

    def poll(self, stage, tick, game_mask, active):
        """Poll one stage tick; active gates one response round."""
        if self._closed:
            return []
        if type(stage) is not int or stage not in STAGES:
            raise ValueError("Stage must be an integer from 1 through 6")
        if type(active) is not bool:
            raise TypeError("active must be a boolean")

        events = []
        stage_changed = self._stage is not None and stage != self._stage
        if self._driver is not None and (stage_changed or not active):
            events.extend(self._stop_round())
        self._stage = stage

        if not active:
            return events
        if self._driver is None:
            self._start_round(stage)
        events.extend(self._annotate(self._driver.poll(tick, game_mask, True), stage))
        return events

    def close(self):
        """Release any held key and make subsequent polls inert."""
        events = self._stop_round()
        self._closed = True
        return events
