"""Hardware-free tests for verified Practice-screen speech transitions."""

import unittest

from duckstation_practice_speech import PracticeSpeechReader, STATE_SIZE


def state(*, panel=True, phase=0):
    data = bytearray(STATE_SIZE)
    data[0:4] = (0x400000 if panel else 0).to_bytes(4, "little")
    data[0x1C:0x20] = phase.to_bytes(4, "little")
    return bytes(data)


class PracticeSpeechReaderTests(unittest.TestCase):
    def test_entry_and_changed_feedback_are_spoken_once(self):
        reader = PracticeSpeechReader()
        current = state(phase=0)

        self.assertEqual(reader.poll(current, True), ["Practice.", "Exactly!"])
        self.assertEqual(reader.hint(),
                         "Look at the bar, press the Triangle button. X Exit.")
        self.assertEqual(reader.poll(current, True), [])
        self.assertEqual(reader.poll(state(phase=1), True), ["You are too quick."])
        self.assertEqual(reader.poll(state(phase=1), True), [])

    def test_blank_panel_allows_the_same_feedback_to_repeat_later(self):
        reader = PracticeSpeechReader()
        self.assertEqual(reader.poll(state(phase=0), True), ["Practice.", "Exactly!"])

        self.assertEqual(reader.poll(state(panel=False, phase=0), True), [])
        self.assertEqual(reader.hint(),
                         "Look at the bar, press the Triangle button. X Exit.")
        self.assertEqual(reader.poll(state(phase=0), True), ["Exactly!"])

    def test_exit_clears_hint_and_next_entry_gets_heading_again(self):
        reader = PracticeSpeechReader()
        self.assertEqual(reader.poll(state(phase=8), True),
                         ["Practice.", "You wanna try again?"])
        self.assertEqual(reader.hint(), "Push the Circle button to try again. X Exit.")

        self.assertEqual(reader.poll(state(phase=8), False), [])
        self.assertEqual(reader.hint(), "")
        self.assertEqual(reader.poll(state(phase=8), True),
                         ["Practice.", "You wanna try again?"])

    def test_unknown_panel_clears_hint_and_invalid_state_resets_reader(self):
        reader = PracticeSpeechReader()
        self.assertEqual(reader.poll(state(phase=0), True), ["Practice.", "Exactly!"])
        self.assertEqual(reader.poll(state(phase=3), True), [])
        self.assertEqual(reader.hint(), "")

        self.assertEqual(reader.poll(b"short", True), [])
        self.assertEqual(reader.hint(), "")
        self.assertEqual(reader.poll(state(phase=2), True), ["Practice.", "You are too slow."])
        self.assertEqual(reader.poll(state(phase=2), 1), [])
        self.assertEqual(reader.hint(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
