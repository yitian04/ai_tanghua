"""Open folders in the local desktop without invoking a shell or opening a file."""
from pathlib import Path
import os
import subprocess
import sys


def show_in_folder(path: Path, *, select: bool = False) -> None:
    path = Path(path)
    if select:
        if not path.is_file(): raise ValueError('文件已删除或移动，请刷新素材库。')
    elif not path.is_dir():
        raise ValueError('文件夹不存在。')
    if sys.platform == 'win32':
        if select: _windows_select(path)
        else: os.startfile(str(path))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', '-R', str(path)] if select else ['open', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path.parent if select else path)])


def _windows_select(path: Path) -> None:
    # PIDLs preserve Unicode, commas and spaces without Explorer command parsing.
    import ctypes
    from ctypes import wintypes
    shell = ctypes.WinDLL('shell32')
    ole = ctypes.WinDLL('ole32')
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    shell.SHParseDisplayName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD, ctypes.c_void_p]
    shell.SHParseDisplayName.restype = ctypes.c_long
    shell.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, wintypes.DWORD]
    shell.SHOpenFolderAndSelectItems.restype = ctypes.c_long
    initialized = ole.CoInitializeEx(None, 2)
    if initialized < 0 and initialized != -2147417850:  # RPC_E_CHANGED_MODE
        raise OSError(f'无法打开文件夹（0x{initialized & 0xffffffff:08X}）。')
    item = ctypes.c_void_p()
    try:
        result = shell.SHParseDisplayName(str(path), None, ctypes.byref(item), 0, None)
        if result >= 0: result = shell.SHOpenFolderAndSelectItems(item, 0, None, 0)
        if result < 0: raise OSError(f'无法在文件夹中显示文件（0x{result & 0xffffffff:08X}）。')
    finally:
        if item: ole.CoTaskMemFree(item)
        if initialized >= 0: ole.CoUninitialize()
