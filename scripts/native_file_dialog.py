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


def choose_file(title, label, pattern):
    api = ctypes.WinDLL('comdlg32', use_last_error=True)
    api.GetOpenFileNameW.argtypes = [ctypes.POINTER(_OPENFILENAMEW)]
    api.GetOpenFileNameW.restype = W.BOOL
    filename = ctypes.create_unicode_buffer(32768)
    dialog = _OPENFILENAMEW()
    dialog.lStructSize = ctypes.sizeof(dialog)
    dialog.lpstrFilter = f'{label}\0{pattern}\0All files\0*.*\0\0'
    dialog.lpstrFile = ctypes.cast(filename, W.LPWSTR)
    dialog.nMaxFile = len(filename)
    dialog.lpstrTitle = title
    dialog.Flags = 0x00080000 | 0x1000 | 0x800 | 0x8  # Explorer, existing file/path, no cwd change.
    if api.GetOpenFileNameW(ctypes.byref(dialog)):
        return filename.value
    error = api.CommDlgExtendedError()
    if error:
        raise OSError(f'Windows file selection failed ({error}).')
    return None
