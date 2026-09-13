"""Small accessible Windows menu built from standard Win32 controls.

The launcher uses a native list box so Windows screen readers can review its
real text, role, and selection. No GUI package or custom accessibility provider
is required. Importing this module is safe on non-Windows systems; creating a
window is Windows-only.
"""

from collections import deque
import ctypes
from ctypes import wintypes
import os


WINDOW_TITLE = "Parappa Access"
CLOSE_TOKEN = "__close__"
native_speech = True

_CLASS_NAME = "ParappaAccessNativeMenu"
_LIST_ID = 1001
_instances = {}
_api = None
_class_registered = False

_LRESULT = ctypes.c_ssize_t
_WPARAM = ctypes.c_size_t
_LPARAM = ctypes.c_ssize_t
_UINT_PTR = ctypes.c_size_t
_DWORD_PTR = ctypes.c_size_t
_CALLBACK = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
_WNDPROC = _CALLBACK(_LRESULT, ctypes.c_void_p, ctypes.c_uint,
                     _WPARAM, _LPARAM)
_SUBCLASSPROC = _CALLBACK(_LRESULT, ctypes.c_void_p, ctypes.c_uint,
                          _WPARAM, _LPARAM, _UINT_PTR, _DWORD_PTR)


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", _WPARAM),
        ("lParam", _LPARAM),
        ("time", ctypes.c_uint),
        ("pt", _POINT),
        ("lPrivate", ctypes.c_uint),
    ]


class _CREATESTRUCTW(ctypes.Structure):
    _fields_ = [
        ("lpCreateParams", ctypes.c_void_p),
        ("hInstance", ctypes.c_void_p),
        ("hMenu", ctypes.c_void_p),
        ("hwndParent", ctypes.c_void_p),
        ("cy", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("y", ctypes.c_int),
        ("x", ctypes.c_int),
        ("style", ctypes.c_long),
        ("lpszName", ctypes.c_wchar_p),
        ("lpszClass", ctypes.c_wchar_p),
        ("dwExStyle", ctypes.c_uint),
    ]


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("style", ctypes.c_uint),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
        ("hIconSm", ctypes.c_void_p),
    ]


class _MINMAXINFO(ctypes.Structure):
    _fields_ = [
        ("ptReserved", _POINT),
        ("ptMaxSize", _POINT),
        ("ptMaxPosition", _POINT),
        ("ptMinTrackSize", _POINT),
        ("ptMaxTrackSize", _POINT),
    ]


def _load_api():
    """Load Win32 entry points with pointer-sized signatures for x64 safety."""
    global _api
    if _api is not None:
        return _api
    if os.name != "nt":
        raise OSError("The native Parappa Access menu requires Windows.")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    user32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
    user32.RegisterClassExW.restype = ctypes.c_ushort
    user32.CreateWindowExW.argtypes = [
        ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = ctypes.c_void_p
    user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                      _WPARAM, _LPARAM]
    user32.DefWindowProcW.restype = _LRESULT
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, _WPARAM, _LPARAM]
    user32.PostMessageW.restype = ctypes.c_int
    user32.GetMessageW.argtypes = [ctypes.POINTER(_MSG), ctypes.c_void_p,
                                   ctypes.c_uint, ctypes.c_uint]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
    user32.TranslateMessage.restype = ctypes.c_int
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]
    user32.DispatchMessageW.restype = _LRESULT
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.ShowWindow.restype = ctypes.c_int
    user32.UpdateWindow.argtypes = [ctypes.c_void_p]
    user32.UpdateWindow.restype = ctypes.c_int
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow.restype = ctypes.c_int
    user32.SetFocus.argtypes = [ctypes.c_void_p]
    user32.SetFocus.restype = ctypes.c_void_p
    user32.SetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    user32.SetWindowTextW.restype = ctypes.c_int
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                    _WPARAM, _LPARAM]
    user32.SendMessageW.restype = _LRESULT
    user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = ctypes.c_int
    user32.MoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int]
    user32.MoveWindow.restype = ctypes.c_int
    user32.DestroyWindow.argtypes = [ctypes.c_void_p]
    user32.DestroyWindow.restype = ctypes.c_int
    user32.IsWindow.argtypes = [ctypes.c_void_p]
    user32.IsWindow.restype = ctypes.c_int
    user32.GetSysColorBrush.argtypes = [ctypes.c_int]
    user32.GetSysColorBrush.restype = ctypes.c_void_p
    user32.LoadCursorW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.LoadCursorW.restype = ctypes.c_void_p
    user32.NotifyWinEvent.argtypes = [ctypes.c_uint, ctypes.c_void_p,
                                      ctypes.c_long, ctypes.c_long]
    user32.NotifyWinEvent.restype = None
    user32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                   ctypes.c_wchar_p, ctypes.c_uint]
    user32.MessageBoxW.restype = ctypes.c_int

    if hasattr(user32, "SetWindowLongPtrW"):
        user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                             _LPARAM]
        user32.SetWindowLongPtrW.restype = _LPARAM
        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = _LPARAM
    else:  # pragma: no cover - 32-bit Windows compatibility
        user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                          ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
        user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long

    comctl32.SetWindowSubclass.argtypes = [ctypes.c_void_p, _SUBCLASSPROC,
                                           _UINT_PTR, _DWORD_PTR]
    comctl32.SetWindowSubclass.restype = ctypes.c_int
    comctl32.RemoveWindowSubclass.argtypes = [ctypes.c_void_p, _SUBCLASSPROC,
                                              _UINT_PTR]
    comctl32.RemoveWindowSubclass.restype = ctypes.c_int
    comctl32.DefSubclassProc.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                         _WPARAM, _LPARAM]
    comctl32.DefSubclassProc.restype = _LRESULT
    gdi32.GetStockObject.argtypes = [ctypes.c_int]
    gdi32.GetStockObject.restype = ctypes.c_void_p

    class _Api:
        pass

    _api = _Api()
    _api.user32 = user32
    _api.kernel32 = kernel32
    _api.comctl32 = comctl32
    _api.gdi32 = gdi32
    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    _api.instance = kernel32.GetModuleHandleW(None)
    return _api


def _set_user_data(hwnd, value):
    api = _load_api()
    setter = getattr(api.user32, "SetWindowLongPtrW", api.user32.SetWindowLongW)
    setter(hwnd, -21, int(value))  # GWLP_USERDATA


def _get_user_data(hwnd):
    api = _load_api()
    getter = getattr(api.user32, "GetWindowLongPtrW", api.user32.GetWindowLongW)
    return int(getter(hwnd, -21))


def _window_proc(hwnd, message, wparam, lparam):
    api = _load_api()
    if message == 0x0081:  # WM_NCCREATE
        create = ctypes.cast(lparam, ctypes.POINTER(_CREATESTRUCTW)).contents
        token = int(create.lpCreateParams or 0)
        instance = _instances.get(token)
        if instance is not None:
            instance._hwnd = hwnd
            _set_user_data(hwnd, token)
    if message == 0x0081:
        token = int(ctypes.cast(lparam, ctypes.POINTER(_CREATESTRUCTW)).contents.lpCreateParams or 0)
    else:
        token = _get_user_data(hwnd)
    instance = _instances.get(token)
    if instance is None:
        return api.user32.DefWindowProcW(hwnd, message, wparam, lparam)
    try:
        result = instance._window_proc(hwnd, message, wparam, lparam)
    except BaseException as exc:  # propagate callback failures at read_key()
        instance._callback_error = exc
        result = 0
    if message == 0x0082:  # WM_NCDESTROY
        _instances.pop(token, None)
        instance._hwnd = None
    return result


_GLOBAL_WNDPROC = _WNDPROC(_window_proc)


def _register_window_class():
    global _class_registered
    if _class_registered:
        return
    api = _load_api()
    window_class = _WNDCLASSEXW()
    window_class.cbSize = ctypes.sizeof(_WNDCLASSEXW)
    window_class.style = 0x0002 | 0x0001  # CS_HREDRAW | CS_VREDRAW
    window_class.lpfnWndProc = _GLOBAL_WNDPROC
    window_class.hInstance = api.instance
    window_class.hCursor = api.user32.LoadCursorW(None, ctypes.c_void_p(32512))
    window_class.hbrBackground = api.user32.GetSysColorBrush(5)  # COLOR_WINDOW
    window_class.lpszClassName = _CLASS_NAME
    if not api.user32.RegisterClassExW(ctypes.byref(window_class)):
        error = ctypes.get_last_error()
        if error != 1410:  # ERROR_CLASS_ALREADY_EXISTS
            raise ctypes.WinError(error)
    _class_registered = True


def _raise_winerror():
    error = ctypes.get_last_error()
    raise ctypes.WinError(error)


class WindowMenu:
    """One reusable native launcher window with a selectable list box."""

    def __init__(self):
        self._hwnd = None
        self._heading_hwnd = None
        self._list_hwnd = None
        self._instructions_hwnd = None
        self._list_subclass_proc = None
        self._events = deque()
        self._tasks = deque()
        self._active = False
        self._selected = 0
        self._items = []
        self._title = ""
        self._instructions = ""
        self._callback_error = None
        self._font = None
        self._name_overrides = None

    def _create_window(self):
        if self._hwnd and _load_api().user32.IsWindow(self._hwnd):
            return
        _register_window_class()
        api = _load_api()
        token = id(self)
        _instances[token] = self
        hwnd = api.user32.CreateWindowExW(
            0x00040000, _CLASS_NAME, WINDOW_TITLE, 0x00CF0000,  # WS_EX_APPWINDOW, WS_OVERLAPPEDWINDOW
            0x80000000, 0x80000000, 780, 580,  # CW_USEDEFAULT
            None, None, api.instance, ctypes.c_void_p(token),
        )
        if not hwnd:
            _instances.pop(token, None)
            _raise_winerror()
        self._hwnd = hwnd
        self._font = api.gdi32.GetStockObject(17)  # DEFAULT_GUI_FONT

    def _destroy_children(self):
        self._clear_short_names()
        api = _load_api()
        if self._list_hwnd and api.user32.IsWindow(self._list_hwnd):
            if self._list_subclass_proc is not None:
                api.comctl32.RemoveWindowSubclass(self._list_hwnd,
                                                  self._list_subclass_proc,
                                                  id(self))
        for name in ("_list_hwnd", "_instructions_hwnd", "_heading_hwnd"):
            child = getattr(self, name)
            if child and api.user32.IsWindow(child):
                api.user32.DestroyWindow(child)
            setattr(self, name, None)
        self._list_subclass_proc = None

    def _create_child(self, class_name, text, style, control_id=0):
        api = _load_api()
        hwnd = api.user32.CreateWindowExW(
            0, class_name, text,
            0x40000000 | 0x10000000 | style,  # WS_CHILD | WS_VISIBLE
            0, 0, 1, 1, self._hwnd,
            ctypes.c_void_p(control_id) if control_id else None,
            api.instance, None,
        )
        if not hwnd:
            _raise_winerror()
        if self._font:
            api.user32.SendMessageW(hwnd, 0x0030, self._font, 1)  # WM_SETFONT
        return hwnd

    def _populate(self):
        api = _load_api()
        user32 = api.user32
        user32.SendMessageW(self._list_hwnd, 0x0184, 0, 0)  # LB_RESETCONTENT
        for key, label in self._items:
            text = ctypes.create_unicode_buffer((f"{key}. {label}" if key else label))
            user32.SendMessageW(self._list_hwnd, 0x0180, 0, ctypes.cast(text, ctypes.c_void_p).value)  # LB_ADDSTRING
        user32.SendMessageW(self._list_hwnd, 0x0186, self._selected, 0)  # LB_SETCURSEL
        self._set_horizontal_extent()

    def _set_horizontal_extent(self):
        """Keep long device names reachable with the list box's H scrollbar."""
        api = _load_api()
        longest = max((len((f"{key}. {label}" if key else label)) for key, label in self._items), default=0)
        # The stock GUI font averages under 10 pixels at standard scaling. The
        # generous estimate keeps full text reachable without a custom draw.
        extent = max(240, longest * 12 + 32)
        api.user32.SendMessageW(self._list_hwnd, 0x0194, extent, 0)  # LB_SETHORIZONTALEXTENT

    def _layout(self, width, height):
        if not self._heading_hwnd or not self._list_hwnd:
            return
        api = _load_api()
        width = max(520, int(width))
        height = max(380, int(height))
        margin = 18
        heading_height = 34
        footer_height = 48
        top = 14
        list_top = top + heading_height + 8
        list_height = max(170, height - list_top - footer_height - 30)
        list_width = width - margin * 2
        footer_top = list_top + list_height + 10
        api.user32.MoveWindow(self._heading_hwnd, margin, top,
                              list_width, heading_height, 1)
        api.user32.MoveWindow(self._list_hwnd, margin, list_top,
                              list_width, list_height, 1)
        api.user32.MoveWindow(self._instructions_hwnd, margin, footer_top,
                              list_width, footer_height, 1)

    def _notify_selection(self, same=False):
        if not self._list_hwnd or not self._items:
            return
        index = max(0, min(self._selected, len(self._items) - 1))
        # A repeated selection (for example Enter on the current practice
        # sound) has no selection delta, so report focus to request a fresh read.
        event = 0x8005 if same else 0x8006  # FOCUS or SELECTION
        _load_api().user32.NotifyWinEvent(event, self._list_hwnd, -4, index + 1)

    def _window_proc(self, hwnd, message, wparam, lparam):
        api = _load_api()
        if message == 0x8001:  # WM_APP + 1: work marshalled from an audio worker
            while self._tasks:
                self._tasks.popleft()()
            return 0
        if message == 0x0007 or (message == 0x0006 and (wparam & 0xFFFF)):
            # WM_SETFOCUS / active WM_ACTIVATE: Alt+Tab returns focus to the
            # top-level window. Keyboard input belongs to the current list.
            if self._active and self._list_hwnd:
                self._clear_short_names()
                api.user32.SetFocus(self._list_hwnd)
                return 0
        if message == 0x0005:  # WM_SIZE
            self._layout(lparam & 0xFFFF, (lparam >> 16) & 0xFFFF)
            return 0
        if message == 0x0024:  # WM_GETMINMAXINFO
            info = ctypes.cast(lparam, ctypes.POINTER(_MINMAXINFO)).contents
            info.ptMinTrackSize.x = 540
            info.ptMinTrackSize.y = 420
            return 0
        if message == 0x0010:  # WM_CLOSE: hide and return a stable token
            if self._active:
                self._events.clear()
                self._events.append(CLOSE_TOKEN)
                api.user32.ShowWindow(hwnd, 0)  # SW_HIDE
            return 0
        if message == 0x0111:  # WM_COMMAND from standard list box
            control_id = wparam & 0xFFFF
            notification = (wparam >> 16) & 0xFFFF
            if control_id == _LIST_ID and notification in (1, 2):
                current = api.user32.SendMessageW(self._list_hwnd, 0x0188, 0, 0)  # LB_GETCURSEL
                if current >= 0:
                    self._selected = int(current)
                    if notification == 1:  # LBN_SELCHANGE (mouse)
                        self._events.append(f"select:{current}")
                    elif notification == 2:  # LBN_DBLCLK
                        self._events.append("\r")
                return 0
        if message == 0x0082:  # WM_NCDESTROY
            return api.user32.DefWindowProcW(hwnd, message, wparam, lparam)
        return api.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _list_proc(self, hwnd, message, wparam, lparam, _subclass_id, _ref_data):
        """Translate input before the list box changes a different selection."""
        api = _load_api()
        if message == 0x0100:  # WM_KEYDOWN
            virtual_key = int(wparam)
            arrows = {0x26: "up", 0x28: "down", 0x25: "left", 0x27: "right"}
            if virtual_key in arrows:
                self._events.append(arrows[virtual_key])
                return 0
            if virtual_key in (0x0D, 0x1B, 0x08):  # Enter, Escape, Backspace
                self._events.append({0x0D: "\r", 0x1B: "\x1b", 0x08: "\x08"}[virtual_key])
                return 0
            if 0x30 <= virtual_key <= 0x39:  # top-row digits
                self._events.append(chr(virtual_key))
                return 0
            if 0x60 <= virtual_key <= 0x69:  # numeric keypad digits
                self._events.append(str(virtual_key - 0x60))
                return 0
            if 0x41 <= virtual_key <= 0x5A:  # launcher helper letters
                self._events.append(chr(virtual_key).lower())
                return 0
            if virtual_key == 0x70:  # F1, if the app uses it
                self._events.append("\x00")
                return 0
        if message == 0x0102:  # WM_CHAR already handled by WM_KEYDOWN
            return 0
        if message == 0x0104:  # WM_SYSKEYDOWN: let Alt+F4 close the window
            if int(wparam) == 0x73:  # Alt+F4
                return api.comctl32.DefSubclassProc(hwnd, message, wparam, lparam)
        return api.comctl32.DefSubclassProc(hwnd, message, wparam, lparam)

    def show(self, title, items, selected, instructions):
        self._create_window()
        api = _load_api()
        self._destroy_children()
        self._events.clear()
        self._callback_error = None
        self._items = list(items)
        self._selected = max(0, min(int(selected or 0), max(0, len(self._items) - 1)))
        title = str(title)
        instructions = str(instructions)

        self._heading_hwnd = self._create_child(
            "STATIC", title, 0x00000000 | 0x00000080, 1000)  # SS_LEFT | SS_NOPREFIX
        # This standard static preceding the list labels it for screen readers.
        self._list_hwnd = self._create_child(
            "LISTBOX", "", 0x00000001 | 0x00000040 | 0x00000100 |
            0x00001000 | 0x00200000 | 0x00100000 | 0x00010000, _LIST_ID)
        self._instructions_hwnd = self._create_child(
            "STATIC", instructions, 0x00000000 | 0x00000080, 1003)

        self._title = title
        self._instructions = instructions
        self._list_subclass_proc = _SUBCLASSPROC(self._list_proc)
        if not api.comctl32.SetWindowSubclass(self._list_hwnd,
                                              self._list_subclass_proc,
                                              id(self), id(self)):
            _raise_winerror()
        self._populate()
        rectangle = wintypes.RECT()
        api.user32.GetClientRect(self._hwnd, ctypes.byref(rectangle))
        self._layout(rectangle.right, rectangle.bottom)
        self._active = True
        api.user32.ShowWindow(self._hwnd, 5)  # SW_SHOW
        api.user32.SetForegroundWindow(self._hwnd)
        api.user32.SetFocus(self._list_hwnd)
        api.user32.UpdateWindow(self._hwnd)

    def call_soon(self, callback):
        """Wake the GUI loop; workers never open dialogs or call screen readers."""
        if self._hwnd:
            self._tasks.append(callback)
            _load_api().user32.PostMessageW(self._hwnd, 0x8001, 0, 0)

    def show_message(self, message, instructions="Press Enter to continue."):
        self.show("Message", [("0", str(message))], 0, instructions)

    def _clear_short_names(self):
        if self._name_overrides is not None:
            self._name_overrides.clear()

    def move(self, selected, advance_caret=False):
        self._clear_short_names()
        del advance_caret  # Native focus events replace the console caret trick.
        if not self._list_hwnd or not self._items:
            return
        selected = max(0, min(int(selected), len(self._items) - 1))
        same = selected == self._selected
        self._selected = selected
        api = _load_api()
        api.user32.SendMessageW(self._list_hwnd, 0x0186, selected, 0)  # LB_SETCURSEL
        if same:
            self._notify_selection(same=True)

    def update(self, items, selected, advance_caret=False, spoken_value=None):
        del advance_caret
        if not self._list_hwnd:
            self.show("Menu", items, selected, "")
            return
        user32 = _load_api().user32
        self._clear_short_names()
        items = list(items)
        previous = self._items
        self._items = items
        self._selected = max(0, min(int(selected), max(0, len(items) - 1)))
        if len(previous) != len(items):
            self._populate()
        else:
            # Keep the same list/focus and replace only changed strings. Rebuilding
            # the page makes a screen reader announce its heading again.
            for index, item in enumerate(items):
                if item != previous[index]:
                    text = ctypes.create_unicode_buffer((f"{item[0]}. {item[1]}" if item[0] else item[1]))
                    user32.SendMessageW(self._list_hwnd, 0x0182, index, 0)  # LB_DELETESTRING
                    user32.SendMessageW(self._list_hwnd, 0x0181, index,
                                        ctypes.cast(text, ctypes.c_void_p).value)  # LB_INSERTSTRING
            if spoken_value is not None:
                if self._name_overrides is None:
                    from native_accessible_name import NameOverrides
                    self._name_overrides = NameOverrides()
                self._name_overrides.set(self._list_hwnd, self._selected + 1, spoken_value)
            user32.SendMessageW(self._list_hwnd, 0x0186, self._selected, 0)
            self._set_horizontal_extent()
        # LB_SETCURSEL supplies the native focus/selection notification.

    @staticmethod
    def _text(hwnd):
        if not hwnd:
            return ""
        api = _load_api()
        length = api.user32.SendMessageW(hwnd, 0x000E, 0, 0)  # WM_GETTEXTLENGTH
        buffer = ctypes.create_unicode_buffer(max(1, int(length) + 1))
        api.user32.SendMessageW(hwnd, 0x000D, len(buffer), ctypes.cast(buffer, ctypes.c_void_p).value)
        return buffer.value

    def finish(self):
        self._active = False
        self._events.clear()
        if self._hwnd and _load_api().user32.IsWindow(self._hwnd):
            _load_api().user32.ShowWindow(self._hwnd, 0)  # SW_HIDE

    def shutdown(self):
        self.finish()
        if self._hwnd and _load_api().user32.IsWindow(self._hwnd):
            self._destroy_children()
            _load_api().user32.DestroyWindow(self._hwnd)
        self._hwnd = None
        self._active = False
        self._tasks.clear()
        if self._name_overrides is not None:
            self._name_overrides.close()
            self._name_overrides = None

    def is_active(self):
        return self._active

    def read_key(self):
        if not self._active:
            return ""
        api = _load_api()
        while self._active:
            if self._callback_error is not None:
                error = self._callback_error
                self._callback_error = None
                raise RuntimeError("Native menu window callback failed") from error
            if self._events:
                value = self._events.popleft()
                if value == CLOSE_TOKEN:
                    self._active = False
                return value
            message = _MSG()
            result = api.user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result == -1:
                _raise_winerror()
            if result == 0:
                self._events.clear()
                self._active = False
                return CLOSE_TOKEN
            api.user32.TranslateMessage(ctypes.byref(message))
            api.user32.DispatchMessageW(ctypes.byref(message))
        return ""


def message_box(message):
    """Show an accessible native error/status dialog under the same app title."""
    api = _load_api()
    owner = _shared_window._hwnd if _shared_window._hwnd and api.user32.IsWindow(
        _shared_window._hwnd) else None
    api.user32.MessageBoxW(owner, str(message), WINDOW_TITLE, 0x00000010)


# One reusable window is shared by nested launcher pages.
_shared_window = WindowMenu()
window_menu = _shared_window


def show(title, items, selected, instructions):
    return _shared_window.show(title, items, selected, instructions)


def move(selected, advance_caret=False):
    return _shared_window.move(selected, advance_caret=advance_caret)


def update(items, selected, advance_caret=False, spoken_value=None):
    return _shared_window.update(items, selected, advance_caret=advance_caret, spoken_value=spoken_value)


def show_message(message, instructions="Press Enter to continue."):
    return _shared_window.show_message(message, instructions)


def finish():
    return _shared_window.finish()


def shutdown():
    return _shared_window.shutdown()


def is_active():
    return _shared_window.is_active()


def read_key():
    return _shared_window.read_key()


def call_soon(callback):
    return _shared_window.call_soon(callback)
