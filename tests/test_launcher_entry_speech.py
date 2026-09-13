import _bootstrap
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

import launcher_entry_speech


class EntrySpeechTests(unittest.TestCase):
    def test_backend_initializes_lazily_once_and_reuses_it(self):
        backend = Mock()
        context = SimpleNamespace(create_best=Mock(return_value=backend))
        prism = SimpleNamespace(Context=Mock(return_value=context))
        speech = launcher_entry_speech.EntrySpeech()
        output = StringIO()

        with patch.dict(sys.modules, {'prism': prism}), redirect_stdout(output):
            self.assertTrue(speech.say('Parappa Access.'))
            self.assertTrue(speech.say('Arrows to move.'))
            self.assertTrue(speech.stop())

        prism.Context.assert_called_once_with()
        context.create_best.assert_called_once_with()
        self.assertEqual(backend.speak.call_args_list, [
            unittest.mock.call('Parappa Access.', interrupt=True),
            unittest.mock.call('Arrows to move.', interrupt=True),
        ])
        backend.stop.assert_called_once_with()
        self.assertEqual(output.getvalue(), '')

    def test_disabled_entry_speech_does_not_initialize_or_output(self):
        prism = SimpleNamespace(Context=Mock())
        speech = launcher_entry_speech.EntrySpeech(enabled=False)
        output = StringIO()

        with patch.dict(sys.modules, {'prism': prism}), redirect_stdout(output):
            self.assertFalse(speech.say('Parappa Access.'))
            self.assertFalse(speech.stop())

        prism.Context.assert_not_called()
        self.assertEqual(output.getvalue(), '')

    def test_prism_initialization_failure_is_silent_and_not_retried(self):
        prism = SimpleNamespace(Context=Mock(side_effect=RuntimeError('unavailable')))
        speech = launcher_entry_speech.EntrySpeech()
        output = StringIO()

        with patch.dict(sys.modules, {'prism': prism}), redirect_stdout(output):
            self.assertFalse(speech.say('Parappa Access.'))
            self.assertFalse(speech.say('Settings.'))

        prism.Context.assert_called_once_with()
        self.assertEqual(output.getvalue(), '')

    def test_backend_speech_and_stop_failures_are_silent(self):
        backend = Mock()
        backend.speak.side_effect = RuntimeError('speech unavailable')
        backend.stop.side_effect = RuntimeError('stop unavailable')
        context = SimpleNamespace(create_best=Mock(return_value=backend))
        prism = SimpleNamespace(Context=Mock(return_value=context))
        speech = launcher_entry_speech.EntrySpeech()
        output = StringIO()

        with patch.dict(sys.modules, {'prism': prism}), redirect_stdout(output):
            self.assertFalse(speech.say('Parappa Access.'))
            self.assertFalse(speech.say('Settings.'))
            self.assertFalse(speech.stop())

        backend.speak.assert_called_once_with('Parappa Access.', interrupt=True)
        backend.stop.assert_not_called()
        self.assertEqual(output.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
