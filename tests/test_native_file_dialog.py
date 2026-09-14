import _bootstrap
import ctypes
import unittest
from unittest.mock import Mock, patch

import native_file_dialog as picker


def field_pointer(dialog, name):
    return ctypes.c_void_p.from_address(
        ctypes.addressof(dialog) + getattr(picker._OPENFILENAMEW, name).offset).value


class FileDialogTests(unittest.TestCase):
    def test_sequential_pickers_reset_filename_and_use_their_own_filter(self):
        api, user = Mock(), Mock()
        user.GetParent.return_value = 321
        choices = [('Game', '*.ccd;*.img', 'C:\\game.ccd'),
                   ('BIOS image', '*.bin;*.rom', 'C:\\bios.bin')]

        def open_dialog(pointer):
            dialog = ctypes.cast(pointer, ctypes.POINTER(picker._OPENFILENAMEW)).contents
            label, pattern, selected = choices.pop(0)
            self.assertEqual(dialog.nFilterIndex, 1)
            self.assertEqual(ctypes.wstring_at(field_pointer(dialog, 'lpstrFile')), '')
            expected = f'{label} ({pattern})\0{pattern}\0All files (*.*)\0*.*\0\0'
            self.assertEqual(ctypes.wstring_at(field_pointer(dialog, 'lpstrFilter'), len(expected)), expected)
            # Windows reports controls initialized after restoring dialog state.
            header = picker._NMHDR()
            header.code = ctypes.c_uint32(-601).value
            callback = picker._HOOK(dialog.lpfnHook)
            callback(123, 0x4E, 0, ctypes.addressof(header))
            calls = user.SendMessageW.call_args_list[-2:]
            self.assertEqual([c.args[2] for c in calls], [0x480, 0x47C])
            for call in calls:
                self.assertEqual(call.args[:2], (321, 0x468))
                self.assertEqual(ctypes.wstring_at(call.args[3]), '')
            value = ctypes.create_unicode_buffer(selected)
            ctypes.memmove(field_pointer(dialog, 'lpstrFile'), value, ctypes.sizeof(value))
            return True

        api.GetOpenFileNameW.side_effect = open_dialog
        with patch.object(picker.ctypes, 'WinDLL', side_effect=lambda name, **kw: api if name == 'comdlg32' else user):
            self.assertEqual(picker.choose_file('Game', 'Game', '*.ccd;*.img'), 'C:\\game.ccd')
            self.assertEqual(picker.choose_file('BIOS', 'BIOS image', '*.bin;*.rom'), 'C:\\bios.bin')

    def test_cancellation_and_dialog_errors_remain_distinct(self):
        api = Mock()
        api.GetOpenFileNameW.return_value = False
        api.CommDlgExtendedError.return_value = 0
        with patch.object(picker.ctypes, 'WinDLL', return_value=api):
            self.assertIsNone(picker.choose_file('BIOS', 'BIOS', '*.bin'))
            api.CommDlgExtendedError.return_value = 9
            with self.assertRaisesRegex(OSError, 'Windows file selection failed'):
                picker.choose_file('BIOS', 'BIOS', '*.bin')
