"""Standard Windows file selection, exposed to screen readers by Windows."""
import ctypes
from ctypes import wintypes as W


class _OPENFILENAMEW(ctypes.Structure):
    _fields_ = [('lStructSize', W.DWORD), ('hwndOwner', W.HWND), ('hInstance', W.HINSTANCE),
                ('lpstrFilter', W.LPCWSTR), ('lpstrCustomFilter', W.LPWSTR),
                ('nMaxCustFilter', W.DWORD), ('nFilterIndex', W.DWORD),
                ('lpstrFile', W.LPWSTR), ('nMaxFile', W.DWORD),
                ('lpstrFileTitle', W.LPWSTR), ('nMaxFileTitle', W.DWORD),
                ('lpstrInitialDir', W.LPCWSTR), ('lpstrTitle', W.LPCWSTR),
                ('Flags', W.DWORD), ('nFileOffset', W.WORD), ('nFileExtension', W.WORD),
                ('lpstrDefExt', W.LPCWSTR), ('lCustData', ctypes.c_ssize_t),
                ('lpfnHook', ctypes.c_void_p), ('lpTemplateName', W.LPCWSTR),
                ('pvReserved', ctypes.c_void_p), ('dwReserved', W.DWORD), ('FlagsEx', W.DWORD)]


class _NMHDR(ctypes.Structure):
    _fields_ = [('hwndFrom', W.HWND), ('idFrom', ctypes.c_size_t), ('code', W.UINT)]


_HOOK = ctypes.WINFUNCTYPE(ctypes.c_size_t, W.HWND, W.UINT,
                          ctypes.c_size_t, ctypes.c_ssize_t)


def choose_file(title, label, pattern):
    api = ctypes.WinDLL('comdlg32', use_last_error=True)
    api.GetOpenFileNameW.argtypes = [ctypes.POINTER(_OPENFILENAMEW)]
    api.GetOpenFileNameW.restype = W.BOOL
    api.CommDlgExtendedError.restype = W.DWORD
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetParent.argtypes = [W.HWND]
    user.GetParent.restype = W.HWND
    user.SendMessageW.argtypes = [W.HWND, W.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
    user.SendMessageW.restype = ctypes.c_ssize_t
    filename = ctypes.create_unicode_buffer(32768)
    filters = ctypes.create_unicode_buffer(f'{label} ({pattern})\0{pattern}\0All files (*.*)\0*.*\0\0')
    empty = ctypes.create_unicode_buffer('')

    @_HOOK
    def initialize(dialog_child, message, wparam, lparam):
        if message == 0x4E and lparam:  # WM_NOTIFY
            header = ctypes.cast(lparam, ctypes.POINTER(_NMHDR)).contents
            if ctypes.c_int32(header.code).value == -601:  # CDN_INITDONE
                # Clear any filename Windows restored after initializing the
                # controls. Game and BIOS selection must start independently.
                parent = user.GetParent(dialog_child)
                for control in (0x480, 0x47C):  # edt1 and Explorer's cmb13
                    user.SendMessageW(parent, 0x468, control,
                                      ctypes.cast(empty, ctypes.c_void_p).value)
        return 0

    dialog = _OPENFILENAMEW()
    dialog.lStructSize = ctypes.sizeof(dialog)
    dialog.lpstrFilter = ctypes.cast(filters, W.LPCWSTR)
    dialog.nFilterIndex = 1
    dialog.lpstrFile = ctypes.cast(filename, W.LPWSTR)
    dialog.nMaxFile = len(filename)
    dialog.lpstrTitle = title
    dialog.lpfnHook = ctypes.cast(initialize, ctypes.c_void_p)
    # Explorer, existing file/path, no cwd change, initialization hook, resize.
    dialog.Flags = 0x00080000 | 0x1000 | 0x800 | 0x8 | 0x20 | 0x800000
    if api.GetOpenFileNameW(ctypes.byref(dialog)):
        return filename.value
    error = api.CommDlgExtendedError()
    if error:
        raise OSError(f'Windows file selection failed ({error}).')
    return None
