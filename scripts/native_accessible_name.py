"""Small ctypes wrapper for per-child MSAA accessible-name overrides."""

import ctypes
import os
import threading
import uuid


_STDCALL = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
_HRESULT = ctypes.c_long
_DWORD = ctypes.c_uint32
_OBJID_CLIENT = 0xFFFFFFFC
_RPC_E_CHANGED_MODE = 0x80010106


class _GUID(ctypes.Structure):
    _fields_ = (("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8))


def _guid(text):
    value = uuid.UUID(text)
    result = _GUID(value.time_low, value.time_mid, value.time_hi_version,
                   (ctypes.c_ubyte * 8).from_buffer_copy(value.bytes[8:]))
    return result


_CLSID_ACC_PROP_SERVICES = _guid("b5f8350b-0548-48b1-a6ee-88bd00b4a5e7")
_IID_ACC_PROP_SERVICES = _guid("6e26e776-04f0-495d-80e4-3330352e3169")
_PROP_ACC_NAME = _guid("608d3df8-8128-4aa7-a428-f55e49267291")


class NameOverrides:
    """Override child names on one thread; call clear before reusing controls."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("MSAA name overrides are available only on Windows")
        self._thread_id = threading.get_ident()
        self._ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        self._ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, _DWORD)
        self._ole32.CoInitializeEx.restype = _HRESULT
        self._ole32.CoUninitialize.argtypes = ()
        self._ole32.CoUninitialize.restype = None
        self._ole32.CoCreateInstance.argtypes = (
            ctypes.POINTER(_GUID), ctypes.c_void_p, _DWORD,
            ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))
        self._ole32.CoCreateInstance.restype = _HRESULT

        hr = int(self._ole32.CoInitializeEx(None, 2))  # COINIT_APARTMENTTHREADED
        self._uninitialize = hr in (0, 1)  # S_OK or S_FALSE
        if (hr & 0xFFFFFFFF) not in (0, 1, _RPC_E_CHANGED_MODE):
            raise OSError(f"CoInitializeEx failed: 0x{hr & 0xFFFFFFFF:08X}")
        self._pointer = ctypes.c_void_p()
        hr = int(self._ole32.CoCreateInstance(
            ctypes.byref(_CLSID_ACC_PROP_SERVICES), None, 1,
            ctypes.byref(_IID_ACC_PROP_SERVICES), ctypes.byref(self._pointer)))
        if hr & 0x80000000:
            if self._uninitialize:
                self._ole32.CoUninitialize()
            raise OSError(f"IAccPropServices creation failed: 0x{hr & 0xFFFFFFFF:08X}")

        vtable = ctypes.cast(self._pointer, ctypes.POINTER(
            ctypes.POINTER(ctypes.c_void_p))).contents
        self._set_name = _STDCALL(_HRESULT, ctypes.c_void_p, ctypes.c_void_p,
                                  _DWORD, _DWORD, _GUID, ctypes.c_wchar_p)(vtable[7])
        self._clear_props = _STDCALL(_HRESULT, ctypes.c_void_p, ctypes.c_void_p,
                                     _DWORD, _DWORD, ctypes.POINTER(_GUID),
                                     ctypes.c_int)(vtable[9])
        self._release = _STDCALL(_DWORD, ctypes.c_void_p)(vtable[2])
        self._tracked = {}
        self._closed = False

    def _check_thread(self):
        if threading.get_ident() != self._thread_id:
            raise RuntimeError("NameOverrides must be used on its COM owner thread")
        if self._closed:
            raise RuntimeError("NameOverrides is closed")

    @staticmethod
    def _handle(hwnd):
        return int(getattr(hwnd, "value", hwnd) or 0)

    def set(self, hwnd, child_id, text):
        self._check_thread()
        hwnd_value, child_id = self._handle(hwnd), int(child_id)
        hr = int(self._set_name(self._pointer, ctypes.c_void_p(hwnd_value),
                                _OBJID_CLIENT, child_id, _PROP_ACC_NAME, str(text)))
        if hr & 0x80000000:
            raise OSError(f"SetHwndPropStr failed: 0x{hr & 0xFFFFFFFF:08X}")
        self._tracked[(hwnd_value, child_id)] = True

    def clear(self):
        """Clear every tracked name; return False if Windows rejected any clear."""
        self._check_thread()
        ok = True
        for hwnd_value, child_id in tuple(self._tracked):
            prop = _PROP_ACC_NAME
            hr = int(self._clear_props(self._pointer, ctypes.c_void_p(hwnd_value),
                                       _OBJID_CLIENT, child_id, ctypes.byref(prop), 1))
            if hr & 0x80000000:
                ok = False
            else:
                self._tracked.pop((hwnd_value, child_id), None)
        return ok

    def close(self):
        if self._closed:
            return
        self._check_thread()
        try:
            self.clear()
        finally:
            self._release(self._pointer)
            self._pointer = None
            self._closed = True
            if self._uninitialize:
                self._ole32.CoUninitialize()
