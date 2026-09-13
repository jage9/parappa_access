import struct
import unittest

from duckstation_profiles import PROFILES, consumed_events, validate_context


def scene_snapshot(profile, cursor, *, index=2, mode=1, active=1, flags=8, tick=240):
    data = bytearray(0xB0)
    struct.pack_into("<I", data, 0, flags)
    struct.pack_into("<I", data, 0x0C, tick)
    struct.pack_into("<h", data, 0x8A, mode)
    field = next(item for item in profile["cursor_fields"] if item["name"] == cursor)
    struct.pack_into("<I", data, field["pointer_offset"], profile["grid"] + (4 if cursor.endswith("_a") else 24))
    struct.pack_into("<h", data, field["index_offset"], index)
    struct.pack_into("<h", data, field["active_offset"], active)
    return data


class DuckStationProfileTests(unittest.TestCase):
    def test_stage_addresses_and_validation_status(self):
        self.assertEqual(set(PROFILES), {1, 2, 3, 4, 5, 6})
        self.assertEqual([PROFILES[n]["count"] for n in range(1, 7)], [36, 38, 24, 26, 21, 36])
        self.assertEqual(PROFILES[6]["loop_word"], 0x27BDFFD8)
        self.assertTrue(PROFILES[1]["passive_verified"])
        self.assertTrue(PROFILES[3]["allow_initial_index1_to2"])
        self.assertTrue(PROFILES[4]["allow_initial_index1_to2"])
        self.assertFalse(PROFILES[5]["allow_initial_index1_to2"])
        self.assertTrue(PROFILES[6]["allow_initial_index1_to2"])
        self.assertTrue(PROFILES[5]["allow_initial_secondary_minus1_to3"])
        self.assertTrue(PROFILES[6]["allow_initial_secondary_minus1_to3"])
        for profile in PROFILES.values():
            self.assertEqual(profile['cue_emission_enabled'],profile['passive_verified'])
            if profile['passive_verified']:self.assertTrue(profile['passive_evidence'])

    def test_context_validator_separates_context_from_shadow_status(self):
        profile = dict(PROFILES[2],passive_verified=False,cue_emission_enabled=False)
        expected = dict(profile["context_expected"])
        result = validate_context(profile, expected)
        self.assertTrue(result["valid"])
        self.assertFalse(result["passive_verified"])
        expected["grid_count"] += 1
        result = validate_context(profile, expected)
        self.assertFalse(result["valid"])
        self.assertEqual(result["mismatches"][0]["field"], "grid_count")

    def test_primary_post_loop_increment_decodes_consumed_byte(self):
        profile = PROFILES[1]
        previous = scene_snapshot(profile, "primary_a")
        current = bytearray(previous)
        struct.pack_into("<h", current, 0x8C, 3)
        grid = bytearray(profile["count"] * 44)
        grid[4 + (3 - 1)] = 2
        events = consumed_events(previous, current, grid, profile)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["button"], "CIRCLE")
        self.assertEqual(events[0]["index"], 2)
        self.assertEqual(events[0]["stream"], "PRIMARY")

    def test_stage3_and_4_initial_index_one_to_two_decodes_only_with_evidence(self):
        for stage, cursor, lane, button in (
            (3, "primary_a", 7, "R1"),
            (4, "response_a", 5, "L1"),
        ):
            with self.subTest(stage=stage, cursor=cursor):
                profile = PROFILES[stage]
                previous = scene_snapshot(profile, cursor, index=1)
                current = bytearray(previous)
                field = next(item for item in profile["cursor_fields"] if item["name"] == cursor)
                struct.pack_into("<h", current, field["index_offset"], 2)
                grid = bytearray(profile["count"] * 44)
                grid[4 + 1] = lane

                events = consumed_events(previous, current, grid, profile)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["button"], button)
                self.assertEqual(events[0]["index"], 1)
                self.assertEqual(events[0]["post_index"], 2)
                self.assertEqual(events[0]["index_rule"], "initial_1_to_2")

                grid[4 + 1] = 0
                self.assertEqual(consumed_events(previous, current, grid, profile), [])

    def test_stage6_initial_index_one_to_two_decodes_primary_and_response(self):
        profile = PROFILES[6]
        for cursor, stream, lane, button in (
            ("primary_a", "PRIMARY", 1, "TRIANGLE"),
            ("response_a", "RESPONSE", 2, "CIRCLE"),
        ):
            with self.subTest(cursor=cursor):
                previous = scene_snapshot(profile, cursor, index=1, mode=1, active=1)
                current = bytearray(previous)
                field = next(item for item in profile["cursor_fields"] if item["name"] == cursor)
                struct.pack_into("<h", current, field["index_offset"], 2)
                grid = bytearray(profile["count"] * 44)
                grid[4 + 1] = lane

                events = consumed_events(previous, current, grid, profile)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["cursor"], cursor)
                self.assertEqual(events[0]["stream"], stream)
                self.assertEqual(events[0]["button"], button)
                self.assertEqual(events[0]["index"], 1)
                self.assertEqual(events[0]["post_index"], 2)
                self.assertEqual(events[0]["index_rule"], "initial_1_to_2")

    def test_stage6_initial_index_exception_rejects_changed_pointer_mode_or_active(self):
        profile = PROFILES[6]
        for cursor in ("primary_a", "response_a"):
            field = next(item for item in profile["cursor_fields"] if item["name"] == cursor)
            with self.subTest(cursor=cursor, gate="pointer"):
                previous = scene_snapshot(profile, cursor, index=1, mode=1, active=1)
                current = bytearray(previous)
                struct.pack_into("<I", current, field["pointer_offset"], profile["grid"] + 44 + 4)
                struct.pack_into("<h", current, field["index_offset"], 2)
                grid = bytearray(profile["count"] * 44)
                grid[44 + 4 + 1] = 1
                self.assertEqual(consumed_events(previous, current, grid, profile), [])

            with self.subTest(cursor=cursor, gate="mode"):
                previous = scene_snapshot(profile, cursor, index=1, mode=1, active=1)
                current = bytearray(previous)
                struct.pack_into("<h", current, field["index_offset"], 2)
                struct.pack_into("<h", current, 0x8A, 2)
                grid = bytearray(profile["count"] * 44)
                grid[4 + 1] = 1
                self.assertEqual(consumed_events(previous, current, grid, profile), [])

            for before_active, after_active in ((0, 1), (1, 2)):
                with self.subTest(cursor=cursor, gate="active", before=before_active, after=after_active):
                    previous = scene_snapshot(profile, cursor, index=1, mode=1, active=before_active)
                    current = bytearray(previous)
                    struct.pack_into("<h", current, field["index_offset"], 2)
                    struct.pack_into("<h", current, field["active_offset"], after_active)
                    grid = bytearray(profile["count"] * 44)
                    grid[4 + 1] = 1
                    self.assertEqual(consumed_events(previous, current, grid, profile), [])

    def test_initial_index_exception_is_narrow_and_stage_scoped(self):
        profile = PROFILES[3]
        previous = scene_snapshot(profile, "primary_a", index=1)
        grid = bytearray(profile["count"] * 44)
        grid[4 + 1] = 1

        changed_pointer = bytearray(previous)
        field = next(item for item in profile["cursor_fields"] if item["name"] == "primary_a")
        struct.pack_into("<I", changed_pointer, field["pointer_offset"], profile["grid"] + 44 + 4)
        struct.pack_into("<h", changed_pointer, field["index_offset"], 2)
        self.assertEqual(consumed_events(previous, changed_pointer, grid, profile), [])

        wrong_previous_index = scene_snapshot(profile, "primary_a", index=0)
        current = bytearray(wrong_previous_index)
        struct.pack_into("<h", current, field["index_offset"], 2)
        self.assertEqual(consumed_events(wrong_previous_index, current, grid, profile), [])

        previous = scene_snapshot(profile, "primary_a", index=1)
        bad_gate = bytearray(previous)
        struct.pack_into("<h", bad_gate, field["index_offset"], 2)
        struct.pack_into("<h", bad_gate, 0x8A, 3)
        self.assertEqual(consumed_events(previous, bad_gate, grid, profile), [])

        changed_mode_previous = scene_snapshot(profile, "primary_a", index=1, mode=2)
        changed_mode_current = bytearray(changed_mode_previous)
        struct.pack_into("<h", changed_mode_current, field["index_offset"], 2)
        struct.pack_into("<h", changed_mode_current, 0x8A, 1)
        self.assertEqual(consumed_events(changed_mode_previous, changed_mode_current, grid, profile), [])

        bad_flag = bytearray(previous)
        struct.pack_into("<h", bad_flag, field["index_offset"], 2)
        struct.pack_into("<I", bad_flag, 0, 0)
        self.assertEqual(consumed_events(previous, bad_flag, grid, profile), [])

        verified_profile = PROFILES[2]
        previous = scene_snapshot(verified_profile, "primary_a", index=1)
        current = bytearray(previous)
        verified_field = next(item for item in verified_profile["cursor_fields"] if item["name"] == "primary_a")
        struct.pack_into("<h", current, verified_field["index_offset"], 2)
        verified_grid = bytearray(verified_profile["count"] * 44)
        verified_grid[4 + 1] = 1
        self.assertEqual(consumed_events(previous, current, verified_grid, verified_profile), [])

    def test_stage5_and6_secondary_start_minus1_to3_uses_only_exact_observed_byte(self):
        cases = (
            (5, "primary_b", "PRIMARY", 2, "CIRCLE"),
            (5, "response_b", "RESPONSE", 2, "CIRCLE"),
            (6, "primary_b", "PRIMARY", 7, "R1"),
            (6, "response_b", "RESPONSE", 3, "X"),
        )
        for stage, cursor, stream, lane, button in cases:
            with self.subTest(stage=stage, cursor=cursor):
                profile = PROFILES[stage]
                grid = bytearray(profile["count"] * 44)
                grid[24 + 2] = lane
                previous = scene_snapshot(profile, cursor, index=-1, mode=2, active=1)
                current = bytearray(previous)
                field = next(item for item in profile["cursor_fields"] if item["name"] == cursor)
                struct.pack_into("<h", current, field["index_offset"], 3)
                struct.pack_into("<h", current, field["active_offset"], 2)

                events = consumed_events(previous, current, grid, profile)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["stream"], stream)
                self.assertEqual(events[0]["button"], button)
                self.assertEqual(events[0]["index"], 2)
                self.assertEqual(events[0]["post_index"], 3)
                self.assertEqual(events[0]["index_rule"], "initial_secondary_minus1_to3")

                grid[24 + 2] = 0
                self.assertEqual(consumed_events(previous, current, grid, profile), [])
                grid[24 + 2] = lane

                wrong_previous_index = scene_snapshot(profile, cursor, index=0, mode=2, active=1)
                wrong_previous = bytearray(wrong_previous_index)
                struct.pack_into("<h", wrong_previous, field["index_offset"], 3)
                struct.pack_into("<h", wrong_previous, field["active_offset"], 2)
                rejected = consumed_events(wrong_previous_index, wrong_previous, grid, profile)
                self.assertFalse(any("button" in item for item in rejected))

                wrong_mode_previous = scene_snapshot(profile, cursor, index=-1, mode=1, active=1)
                wrong_mode_current = bytearray(wrong_mode_previous)
                struct.pack_into("<h", wrong_mode_current, field["index_offset"], 3)
                struct.pack_into("<h", wrong_mode_current, field["active_offset"], 2)
                struct.pack_into("<h", wrong_mode_current, 0x8A, 2)
                rejected = consumed_events(wrong_mode_previous, wrong_mode_current, grid, profile)
                self.assertFalse(any("button" in item for item in rejected))

                wrong_activation = scene_snapshot(profile, cursor, index=-1, mode=2, active=0)
                wrong_activation_current = bytearray(wrong_activation)
                struct.pack_into("<h", wrong_activation_current, field["index_offset"], 3)
                struct.pack_into("<h", wrong_activation_current, field["active_offset"], 2)
                rejected = consumed_events(wrong_activation, wrong_activation_current, grid, profile)
                self.assertFalse(any("button" in item for item in rejected))

        stage4 = PROFILES[4]
        previous = scene_snapshot(stage4, "primary_b", index=-1, mode=2, active=1)
        current = bytearray(previous)
        field = next(item for item in stage4["cursor_fields"] if item["name"] == "primary_b")
        struct.pack_into("<h", current, field["index_offset"], 3)
        struct.pack_into("<h", current, field["active_offset"], 2)
        stage4_grid = bytearray(stage4["count"] * 44)
        stage4_grid[24 + 2] = 2
        rejected = consumed_events(previous, current, stage4_grid, stage4)
        self.assertFalse(any("button" in item for item in rejected))

    def test_response_secondary_gate_and_lane_decode(self):
        profile = PROFILES[2]
        previous = scene_snapshot(profile, "response_b", mode=2, active=2)
        current = bytearray(previous)
        struct.pack_into("<h", current, 0xA0, 3)
        grid = bytearray(profile["count"] * 44)
        grid[24 + (3 - 1)] = 8
        events = consumed_events(previous, current, grid, profile)
        self.assertEqual([event["button"] for event in events], ["R1"])
        self.assertEqual(events[0]["stream"], "RESPONSE")

    def test_invalid_gate_and_index_jump_never_emit_button(self):
        profile = PROFILES[3]
        previous = scene_snapshot(profile, "primary_b", mode=1, active=2)
        current = bytearray(previous)
        struct.pack_into("<h", current, 0x8E, 3)
        grid = bytearray(profile["count"] * 44)
        grid[24 + 2] = 1
        self.assertEqual(consumed_events(previous, current, grid, profile), [])

        previous = scene_snapshot(profile, "primary_a")
        current = bytearray(previous)
        struct.pack_into("<h", current, 0x8C, 4)
        grid[4 + 3] = 1
        events = consumed_events(previous, current, grid, profile)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["rejected"], "index_jump")
        self.assertNotIn("button", events[0])


if __name__ == "__main__":
    unittest.main()
