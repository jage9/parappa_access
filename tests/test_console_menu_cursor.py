import _bootstrap
import ctypes
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

from console_menu_cursor import BufferInfo, ConsoleMenuCursor, CursorInfo


class ConsoleCursorTests(unittest.TestCase):
    def test_moves_without_output_and_restores_end_after_scrolling(self):
        cursor = ConsoleMenuCursor.__new__(ConsoleMenuCursor)
        cursor.end = cursor.first_row = None
        cursor.selected = None
        cursor.saved_cursor = None
        cursor.width = 0
        cursor.handle = 123
        positions = []
        visibility = []

        def cursor_info(handle, target):
            value = ctypes.cast(target, ctypes.POINTER(CursorInfo)).contents
            value.size, value.visible = 25, True
            return True

        def info(handle, target):
            value = ctypes.cast(target, ctypes.POINTER(BufferInfo)).contents
            value.size.x, value.size.y = 80, 30
            value.window.bottom = 24
            value.attributes = 7
            value.cursor.x, value.cursor.y = 0, 24
            return True

        cursor.api = SimpleNamespace(
            GetConsoleScreenBufferInfo=info,
            GetConsoleCursorInfo=cursor_info,
            SetConsoleCursorInfo=lambda handle, target: visibility.append(
                bool(ctypes.cast(target, ctypes.POINTER(CursorInfo)).contents.visible)),
            GetConsoleMode=Mock(return_value=False),
            SetConsoleMode=Mock(),
            WriteConsoleOutputCharacterW=Mock(),
            WriteConsoleOutputW=Mock(return_value=False),
            SetConsoleTitleW=Mock(),
            FillConsoleOutputCharacterW=Mock(),
            FillConsoleOutputAttribute=Mock(),
            SetConsoleTextAttribute=Mock(),
            SetConsoleCursorPosition=lambda handle, pos: positions.append((pos.x, pos.y)))
        output = StringIO()
        with redirect_stdout(output):
            cursor.show('Main menu', [('1', 'Play'), ('2', 'Learn sounds'),
                                     ('3', 'Settings'), ('0', 'Exit')], 0, 'Arrows select.')
            initial = output.getvalue()
            cursor.move(1)
            cursor.move(3)
            cursor.finish()
        self.assertEqual(output.getvalue(), initial)
        self.assertEqual(positions, [(0, 0), (3, 18), (3, 19), (3, 21), (0, 24)])
        cursor.api.SetConsoleTitleW.assert_called_once_with('Parappa Access')
        clear = cursor.api.FillConsoleOutputCharacterW.call_args.args
        self.assertEqual(clear[1:3], (' ', 2400))
        colors = [call.args[1] for call in cursor.api.FillConsoleOutputAttribute.call_args_list]
        self.assertEqual(colors, [0x0F, 0xF0, 0x0F, 0xF0, 0x0F, 0xF0, 0x0F])
        self.assertEqual(cursor.api.SetConsoleTextAttribute.call_args.args, (123, 7))
        self.assertIsNone(cursor.first_row)
        self.assertEqual(visibility, [False, True])

    def test_page_is_painted_once_and_caret_follows_selected_item(self):
        with redirect_stdout(StringIO()):
            cursor = ConsoleMenuCursor()
        cursor.handle = 123
        def info(handle, target):
            value = ctypes.cast(target, ctypes.POINTER(BufferInfo)).contents
            value.size.x, value.size.y = 80, 30
            value.cursor.x, value.cursor.y = 0, 0
        cursor.api = Mock()
        cursor.api.GetConsoleScreenBufferInfo.side_effect = lambda *args: (info(*args), True)[1]
        cursor.api.GetConsoleCursorInfo.return_value = False
        cursor.api.GetConsoleMode.return_value = False
        cursor.api.WriteConsoleOutputW.return_value = True
        output = StringIO()
        with redirect_stdout(output):
            cursor.show('Settings', [('1', 'Cue panning on'), ('0', 'Back')], 0, 'Arrows move.')
            cursor.move(1)
        self.assertEqual(output.getvalue(), '')
        cursor.api.WriteConsoleOutputW.assert_called_once()
        args = cursor.api.WriteConsoleOutputW.call_args.args
        painted = ''.join(cell.character.unicode for cell in args[1])
        self.assertIn('1. Cue panning on', painted)
        self.assertLess(painted.index('0. Back'), painted.index('Arrows move.'))
        self.assertEqual(cursor.first_row, 1)
        cursor.update([('1', 'Cue panning off'), ('0', 'Back')], 1, advance_caret=True)
        cursor.update([('1', 'Cue panning off'), ('0', 'Back')], 1, advance_caret=True)
        # Clear, initial selection, then arrow selection. Never leave the caret
        # on the page heading where NVDA would announce it after each arrow.
        moves = cursor.api.SetConsoleCursorPosition.call_args_list
        self.assertEqual([(call.args[1].x, call.args[1].y) for call in moves],
                         [(0, 0), (3, 1), (3, 2), (4, 2), (3, 2)])


if __name__ == '__main__':
    unittest.main()
