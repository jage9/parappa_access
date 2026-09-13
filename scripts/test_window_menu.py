"""Bounded integration checks against the real native Win32 controls."""

import ctypes
import os
import sys
from pathlib import Path
import unittest


SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import window_menu


@unittest.skipUnless(os.name == "nt", "native launcher controls require Windows")
class NativeWindowMenuTests(unittest.TestCase):
    def setUp(self):
        self.menu = window_menu.WindowMenu()

    def tearDown(self):
        self.menu.shutdown()

    def _send(self, hwnd, message, wparam=0, lparam=0):
        return window_menu._load_api().user32.SendMessageW(
            hwnd, message, wparam, lparam)

    def _post(self, hwnd, message, wparam=0, lparam=0):
        user32 = window_menu._load_api().user32
        user32.PostMessageW.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
        ]
        user32.PostMessageW.restype = ctypes.c_int
        self.assertTrue(user32.PostMessageW(hwnd, message, wparam, lparam))

    def _list_text(self, index):
        buffer = ctypes.create_unicode_buffer(1024)
        self._send(self.menu._list_hwnd, 0x0189, index,
                   ctypes.cast(buffer, ctypes.c_void_p).value)  # LB_GETTEXT
        return buffer.value

    def test_real_listbox_exposes_item_text_and_native_static_labels(self):
        self.menu.show(
            "Main menu",
            [("1", "Play"), ("2", "Learn sounds"), ("0", "Exit")],
            1,
            "Arrows to move. Enter or number keys select.",
        )
        self.assertTrue(self.menu._hwnd)
        self.assertTrue(self.menu._list_hwnd)
        self.assertEqual(self.menu._text(self.menu._heading_hwnd), "Main menu")
        self.assertEqual(
            self.menu._text(self.menu._instructions_hwnd),
            "Arrows to move. Enter or number keys select.",
        )
        self.assertEqual(self._send(self.menu._list_hwnd, 0x018B), 3)  # LB_GETCOUNT
        self.assertEqual(self._list_text(0), "1. Play")
        self.assertEqual(self._list_text(1), "2. Learn sounds")
        self.assertEqual(self._send(self.menu._list_hwnd, 0x0188), 1)  # LB_GETCURSEL

    def test_getmessage_returns_launcher_keys_without_native_arrow_selection(self):
        self.menu.show("Settings", [("1", "Pan"), ("0", "Back")], 0, "Use arrows.")
        listbox = self.menu._list_hwnd
        self._post(listbox, 0x0100, 0x28)  # WM_KEYDOWN VK_DOWN
        self.assertEqual(self.menu.read_key(), "down")
        # Arrow interception leaves the native row alone until the menu calls move().
        self.assertEqual(self._send(listbox, 0x0188), 0)
        self.menu.move(1)
        self.assertEqual(self._send(listbox, 0x0188), 1)

        cases = ((0x32, "2"), (0x51, "q"), (0x0D, "\r"),
                 (0x1B, "\x1b"), (0x08, "\x08"))
        for virtual_key, expected in cases:
            self._post(listbox, 0x0100, virtual_key)
            self.assertEqual(self.menu.read_key(), expected)

    def test_mouse_selection_token_and_double_click_enter(self):
        self.menu.show("Devices", [("1", "Default"), ("2", "USB output")],
                       0, "Choose a device.")
        self._send(self.menu._list_hwnd, 0x0186, 1)  # LB_SETCURSEL
        command = (1 << 16) | window_menu._LIST_ID  # LBN_SELCHANGE
        self._send(self.menu._hwnd, 0x0111, command, self.menu._list_hwnd)
        self.assertEqual(self.menu.read_key(), "select:1")

        command = (2 << 16) | window_menu._LIST_ID  # LBN_DBLCLK
        self._send(self.menu._hwnd, 0x0111, command, self.menu._list_hwnd)
        self.assertEqual(self.menu.read_key(), "\r")

    def test_long_lists_and_names_remain_scrollable_and_pages_reuse_window(self):
        items = [(str(index), f"Audio output {index} " + ("ProFX device " * 9))
                 for index in range(15)]
        self.menu.show("Audio device", items, 14, "Arrows move. Enter selects.")
        hwnd = self.menu._list_hwnd
        self.assertEqual(self._send(hwnd, 0x018B), 15)
        self.assertGreaterEqual(self._send(hwnd, 0x0193), 240)  # LB_GETHORIZONTALEXTENT
        original_window = self.menu._hwnd
        original_list = hwnd

        self.menu.finish()
        self.menu.show("Volume", [("0", "Back"), ("1", "Cue volume 100 percent")],
                       1, "Use left and right.")
        self.assertEqual(self.menu._hwnd, original_window)
        self.assertNotEqual(self.menu._list_hwnd, original_list)
        self.assertEqual(self.menu._text(self.menu._heading_hwnd), "Volume")
        self.assertEqual(self._send(self.menu._list_hwnd, 0x0188), 1)

    def test_update_keeps_list_handle_and_replaces_native_item_text(self):
        self.menu.show(
            "Settings",
            [("1", "Cue panning off"), ("2", "Audio device System default")],
            0,
            "Use arrows.",
        )
        original_list = self.menu._list_hwnd
        self.menu.update(
            [("1", "Cue panning on"), ("2", "Audio device System default")],
            0, spoken_value="On",
        )
        self.assertEqual(self.menu._list_hwnd, original_list)
        self.assertEqual(self._list_text(0), "1. Cue panning on")
        self.assertEqual(self._list_text(1), "2. Audio device System default")

    def test_reactivation_restores_list_focus_and_keyboard_navigation(self):
        self.menu.show('Settings', [('1', 'Pan'), ('0', 'Back')], 1, 'Arrows')
        api = window_menu._load_api().user32
        api.GetFocus.restype = ctypes.c_void_p
        other = window_menu.WindowMenu()
        try:
            other.show('Other window', [('0', 'Back')], 0, '')
            api.SetFocus(other._list_hwnd)
            self._send(self.menu._hwnd, 0x0006, 1, other._hwnd)  # WM_ACTIVATE
            self.assertEqual(api.GetFocus(), self.menu._list_hwnd)
            self.assertEqual(self._send(self.menu._list_hwnd, 0x0188), 1)
            self._post(api.GetFocus(), 0x0100, 0x26)
            self.assertEqual(self.menu.read_key(), 'up')
        finally:
            other.shutdown()

    def test_worker_task_is_dispatched_by_gui_loop(self):
        self.menu.show('Main', [('0', 'Back')], 0, '')
        import threading
        gui_thread = threading.get_ident()
        observed = []
        def task():
            observed.append(threading.get_ident())
            self._post(self.menu._list_hwnd, 0x0100, 0x0D)
        worker = threading.Thread(target=lambda: self.menu.call_soon(task))
        worker.start()
        worker.join(1)
        self.assertEqual(self.menu.read_key(), '\r')
        self.assertEqual(observed, [gui_thread])

    def test_close_button_returns_token_and_window_can_be_reopened(self):
        self.menu.show("Settings", [("0", "Back")], 0, "Enter returns.")
        self._post(self.menu._hwnd, 0x0010)  # WM_CLOSE
        self.assertEqual(self.menu.read_key(), window_menu.CLOSE_TOKEN)
        self.assertFalse(self.menu.is_active())

        self.menu.show("Main menu", [("1", "Play")], 0, "Enter selects.")
        self._post(self.menu._list_hwnd, 0x0100, 0x0D)
        self.assertEqual(self.menu.read_key(), "\r")


if __name__ == "__main__":
    unittest.main()
