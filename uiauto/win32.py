"""Thin ctypes layer: window enumeration, focus/cursor checks, background capture.

Nothing here sends synthetic mouse or keyboard input.
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass

WIN = sys.platform == "win32"

PW_RENDERFULLCONTENT = 0x2
GW_OWNER = 4
SW_SHOWNOACTIVATE = 4
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


if WIN:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    H, I, U = wintypes.HWND, ctypes.c_int, wintypes.UINT
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, H, wintypes.LPARAM)

    def _sig(fn, argtypes, restype=wintypes.BOOL):
        fn.argtypes, fn.restype = argtypes, restype

    _sig(user32.EnumWindows, [WNDENUMPROC, wintypes.LPARAM])
    _sig(user32.GetWindowTextW, [H, wintypes.LPWSTR, I], I)
    _sig(user32.GetClassNameW, [H, wintypes.LPWSTR, I], I)
    _sig(user32.GetWindowThreadProcessId, [H, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD)
    _sig(user32.IsWindowVisible, [H])
    _sig(user32.IsWindow, [H])
    _sig(user32.IsIconic, [H])
    _sig(user32.GetWindowRect, [H, ctypes.POINTER(wintypes.RECT)])
    _sig(user32.GetForegroundWindow, [], H)
    _sig(user32.GetWindow, [H, U], H)
    _sig(user32.GetCursorPos, [ctypes.POINTER(wintypes.POINT)])
    _sig(user32.PrintWindow, [H, wintypes.HDC, U])
    _sig(user32.GetWindowDC, [H], wintypes.HDC)
    _sig(user32.ReleaseDC, [H, wintypes.HDC], I)
    _sig(user32.ShowWindow, [H, I])
    _sig(user32.SetWindowPos, [H, H, I, I, I, I, U])
    _sig(user32.GetSystemMetrics, [I], I)
    _sig(user32.PostMessageW, [H, U, wintypes.WPARAM, wintypes.LPARAM])
    _sig(gdi32.CreateCompatibleDC, [wintypes.HDC], wintypes.HDC)
    _sig(gdi32.CreateCompatibleBitmap, [wintypes.HDC, I, I], wintypes.HBITMAP)
    _sig(gdi32.SelectObject, [wintypes.HDC, wintypes.HGDIOBJ], wintypes.HGDIOBJ)
    _sig(gdi32.GetDIBits, [wintypes.HDC, wintypes.HBITMAP, U, U, ctypes.c_void_p, ctypes.c_void_p, U], I)
    _sig(gdi32.DeleteObject, [wintypes.HGDIOBJ])
    _sig(gdi32.DeleteDC, [wintypes.HDC])
    _sig(kernel32.OpenProcess, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE)
    _sig(kernel32.QueryFullProcessImageNameW,
         [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)])
    _sig(kernel32.CloseHandle, [wintypes.HANDLE])


def set_dpi_aware() -> None:
    """Per-monitor DPI awareness so rectangles and captures are in physical pixels."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass


@dataclass
class Window:
    hwnd: int
    title: str
    cls: str
    pid: int
    exe: str
    rect: tuple[int, int, int, int]
    iconic: bool
    owned: bool

    @property
    def area(self) -> int:
        l, t, r, b = self.rect
        return max(0, r - l) * max(0, b - t)

    def as_dict(self) -> dict:
        return {"hwnd": hex(self.hwnd), "title": self.title, "class": self.cls, "pid": self.pid,
                "exe": self.exe, "rect": list(self.rect), "minimized": self.iconic, "owned": self.owned}


def process_exe(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(len(buf))
        return buf.value if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        kernel32.CloseHandle(h)


def window_info(hwnd: int) -> Window:
    title = ctypes.create_unicode_buffer(512)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, len(title))
    user32.GetClassNameW(hwnd, cls, len(cls))
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return Window(hwnd, title.value, cls.value, pid.value, process_exe(pid.value),
                  (r.left, r.top, r.right, r.bottom), bool(user32.IsIconic(hwnd)),
                  bool(user32.GetWindow(hwnd, GW_OWNER)))


def enum_windows() -> list[Window]:
    """All visible top-level windows."""
    hwnds: list[int] = []

    @WNDENUMPROC
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            hwnds.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return [window_info(h) for h in hwnds]


def windows_under(root_dir: str) -> list[Window]:
    """Visible top-level windows whose process image lives under root_dir, largest first."""
    root = os.path.normcase(os.path.abspath(root_dir)).rstrip("\\") + "\\"
    ws = [w for w in enum_windows() if os.path.normcase(w.exe).startswith(root) and (w.area or w.iconic)]
    return sorted(ws, key=lambda w: (w.owned, -w.area))


def foreground() -> int:
    return user32.GetForegroundWindow() or 0


def cursor() -> tuple[int, int]:
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def show_noactivate(hwnd: int) -> None:
    """Restore a minimised window without giving it focus."""
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)


def move(hwnd: int, x: int, y: int) -> None:
    user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def close_window(hwnd: int) -> None:
    """Ask a window to close (WM_CLOSE); returns immediately."""
    user32.PostMessageW(hwnd, 0x0010, 0, 0)


def park(hwnd: int) -> None:
    """Move a window beyond the right edge of the virtual screen (still rendered, out of the way)."""
    right = user32.GetSystemMetrics(76) + user32.GetSystemMetrics(78)  # SM_XVIRTUALSCREEN + SM_CXVIRTUALSCREEN
    move(hwnd, right + 200, 0)


def capture(hwnd: int):
    """Capture a window with PrintWindow: works when covered or off-screen, not when minimised."""
    from PIL import Image

    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        raise RuntimeError("window has no area (minimised?)")
    wdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(wdc)
    bmp = gdi32.CreateCompatibleBitmap(wdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        ok = user32.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT)
        gdi32.SelectObject(mdc, old)
        bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        got = gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        if not ok or got != h:
            raise RuntimeError(f"PrintWindow ok={ok}, GetDIBits rows={got}/{h}")
        return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).copy()
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, wdc)


def is_blank(img) -> bool:
    lo, hi = img.convert("L").getextrema()
    return hi - lo < 8
