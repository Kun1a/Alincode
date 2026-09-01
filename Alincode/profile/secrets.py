"""Windows DPAPI 密钥保护封装。"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def protect(value: str) -> bytes:
    """以当前 Windows 用户的 DPAPI 范围加密文本。"""
    return _crypt(value.encode("utf-8"), protect_data=True)


def unprotect(value: bytes) -> str:
    """以当前 Windows 用户的 DPAPI 范围解密文本。"""
    return _crypt(value, protect_data=False).decode("utf-8")


def _crypt(value: bytes, *, protect_data: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("本机 Profile 密钥保护仅支持 Windows")

    raw = (ctypes.c_byte * len(value)).from_buffer_copy(value)
    source = _DataBlob(len(value), raw)
    result = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if protect_data:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)
        )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)
