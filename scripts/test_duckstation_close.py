"""Exit classification without executing the emulator preparation script."""
import ast
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock

source = Path(__file__).with_name('duckstation-compare.py')
node = next(n for n in ast.parse(source.read_text()).body
            if isinstance(n, ast.FunctionDef) and n.name == 'closed_normally')
namespace = {'subprocess': subprocess}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
closed_normally = namespace['closed_normally']

class EmulatorCloseTests(unittest.TestCase):
    def test_only_verified_successful_exit_counts_as_normal_close(self):
        for code in (0, 1, -1, 0xC0000005):
            with self.subTest(code=code):
                process = Mock()
                process.wait.return_value = code
                self.assertEqual(closed_normally(process), code == 0)
                process.wait.assert_called_once_with(timeout=1)

    def test_still_running_or_not_started_is_not_normal_close(self):
        process = Mock()
        process.wait.side_effect = subprocess.TimeoutExpired('DuckStation', 1)
        self.assertFalse(closed_normally(process))
        self.assertFalse(closed_normally(None))

if __name__ == '__main__':
    unittest.main()
