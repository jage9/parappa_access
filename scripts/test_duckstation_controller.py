"""Tests for reversible SDL gamepad bindings in a DuckStation settings INI."""
import unittest

from duckstation_controller import (
    STANDARD_GAMEPAD_BINDINGS,
    add_automatic_controller_bindings,
)


def parse_repeated_ini(text):
    """Parse only the section/key/value shape needed by the fixtures."""
    parsed = {}
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("[") and "]" in stripped:
            section = stripped[1:stripped.index("]")].strip()
            parsed.setdefault(section, {})
            continue
        if section is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split("#", 1)[0].split(";", 1)[0].strip()
        parsed.setdefault(section, {}).setdefault(key.strip(), []).append(value)
    return parsed


class DuckStationControllerConfigTests(unittest.TestCase):
    def setUp(self):
        self.original = (
            "[Audio]\n"
            "OutputDevice = selected endpoint\n"
            "\n"
            "[Pad1]\n"
            "Type = DigitalController\n"
            "Up = Keyboard/Up\n"
            "Down = Keyboard/Down\n"
            "Left = Keyboard/Left\n"
            "Right = Keyboard/Right\n"
            "Triangle = Keyboard/S\n"
            "Circle = Keyboard/D\n"
            "Cross = Keyboard/X\n"
            "Square = Keyboard/Z\n"
            "Select = Keyboard/Backspace\n"
            "Start = Keyboard/Return\n"
            "L1 = Keyboard/Q\n"
            "R1 = Keyboard/R\n"
        )

    def test_adds_sdl_aliases_as_repeated_keys_and_preserves_existing_settings(self):
        configured = add_automatic_controller_bindings(self.original)
        parsed = parse_repeated_ini(configured)

        self.assertEqual(parsed["InputSources"]["SDL"], ["true"])
        self.assertEqual(parsed["Audio"]["OutputDevice"], ["selected endpoint"])
        self.assertEqual(parsed["Pad1"]["Type"], ["DigitalController"])
        self.assertEqual(parsed["Pad1"]["Triangle"], ["Keyboard/S", "SDL-0/Y"])
        self.assertEqual(parsed["Pad1"]["Circle"], ["Keyboard/D", "SDL-0/B"])
        self.assertEqual(parsed["Pad1"]["Cross"], ["Keyboard/X", "SDL-0/A"])
        self.assertEqual(parsed["Pad1"]["Square"], ["Keyboard/Z", "SDL-0/X"])
        self.assertEqual(parsed["Pad1"]["L1"], ["Keyboard/Q", "SDL-0/LeftShoulder"])
        self.assertEqual(parsed["Pad1"]["R1"], ["Keyboard/R", "SDL-0/RightShoulder"])
        self.assertEqual(len(STANDARD_GAMEPAD_BINDINGS), 12)
        self.assertNotIn("Triangle = Keyboard/S,SDL-0/Y", configured)

    def test_existing_aliases_are_kept_and_missing_aliases_are_added_once(self):
        original = self.original.replace(
            "Triangle = Keyboard/S\n", "Triangle = Keyboard/S\nTriangle = SDL-0/Y\n"
        ).replace(
            "Circle = Keyboard/D\n", "Circle = Keyboard/D\nCircle = SDL-0/B\n"
        )
        configured = add_automatic_controller_bindings(original)
        parsed = parse_repeated_ini(configured)

        self.assertEqual(parsed["Pad1"]["Triangle"], ["Keyboard/S", "SDL-0/Y"])
        self.assertEqual(parsed["Pad1"]["Circle"], ["Keyboard/D", "SDL-0/B"])
        self.assertEqual(add_automatic_controller_bindings(configured), configured)

    def test_sdl_false_is_enabled_and_line_comment_is_preserved(self):
        original = self.original.replace("[Audio]", "[InputSources]\nSDL = false ; keep note\n\n[Audio]")
        configured = add_automatic_controller_bindings(original)
        parsed = parse_repeated_ini(configured)

        self.assertEqual(parsed["InputSources"]["SDL"], ["true"])
        self.assertIn("SDL = true ; keep note", configured)

    def test_adds_missing_input_sources_section_and_preserves_crlf(self):
        original = self.original.replace("\n", "\r\n").rstrip("\r\n")
        configured = add_automatic_controller_bindings(original)

        self.assertIn("\r\nTriangle = SDL-0/Y\r\n", configured)
        self.assertIn("[InputSources]\r\nSDL = true\r\n", configured)
        self.assertNotIn("\n", configured.replace("\r\n", ""))

    def test_appends_to_final_pad_section_without_final_newline(self):
        original = "[InputSources]\nSDL = true\n\n[Pad1]\nTriangle = Keyboard/S"
        configured = add_automatic_controller_bindings(original)
        parsed = parse_repeated_ini(configured)

        self.assertEqual(parsed["Pad1"]["Triangle"], ["Keyboard/S", "SDL-0/Y"])
        self.assertIn("Triangle = Keyboard/S\nUp = SDL-0/DPadUp\n", configured)
        self.assertIn("\nTriangle = SDL-0/Y\n", configured)

    def test_nonzero_player_id_is_explicit_and_keyboard_stays_bound(self):
        configured = add_automatic_controller_bindings(self.original, player_id=2)
        parsed = parse_repeated_ini(configured)

        self.assertEqual(parsed["Pad1"]["Triangle"], ["Keyboard/S", "SDL-2/Y"])

    def test_missing_pad_section_and_invalid_player_id_fail_without_mutating_input(self):
        with self.assertRaisesRegex(ValueError, r"\[Pad1\]"):
            add_automatic_controller_bindings("[Audio]\nOutputDevice=selected\n")
        for value, error in ((True, TypeError), ("0", TypeError), (-1, ValueError)):
            with self.subTest(value=value), self.assertRaises(error):
                add_automatic_controller_bindings(self.original, player_id=value)
        self.assertIn("Triangle = Keyboard/S\n", self.original)


if __name__ == "__main__":
    unittest.main()
