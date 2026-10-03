"""oswin.py — Windows OS-level input (real hardware mouse/keyboard) + CDP helpers.

Follows the local xhs-search skill: genuine SetCursorPos/mouse_event clicks (not synthetic CDP
input), viewport-origin calibration verified by a real click, DOM/media read over CDP.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PORT = 9222
PROFILE = r"C:\Users\32464\Desktop\wenxian\_tools\edge-profile"
DOWNLOADS = r"C:\Users\32464\Desktop\wenxian\_tools\browser-downloads"
BROWSER = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CAL_PATH = r"C:\Users\32464\Desktop\wenxian\_tools\osclick-cal.json"

u32 = ctypes.WinDLL("user32", use_last_error=True)
g32 = ctypes.WinDLL("gdi32", use_last_error=True)


class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]
    _anonymous_ = ("i",)
    _fields_ = [("type", wt.DWORD), ("i", _I)]


# ---------- real hardware input ----------
def move(x, y):
    u32.SetCursorPos(int(x), int(y))


def cursor_pos():
    pt = wt.POINT()
    u32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def click(x, y, glide_from=None, steps=8):
    if glide_from:
        x0, y0 = glide_from
        for i in range(1, steps + 1):
            move(x0 + (x - x0) * i / steps, y0 + (y - y0) * i / steps)
            time.sleep(0.012)
    move(x, y)
    time.sleep(0.08)
    u32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    time.sleep(0.06)
    u32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
    time.sleep(0.06)


def wheel(delta=-120, times=1):
    for _ in range(times):
        u32.mouse_event(0x0800, 0, 0, ctypes.c_uint32(delta).value, 0)
        time.sleep(0.1)


VK = {"ENTER": 0x0D, "TAB": 0x09, "ESC": 0x1B, "BACK": 0x08, "CTRL": 0x11, "A": 0x41,
      "C": 0x43, "F": 0x46, "J": 0x4A, "L": 0x4C, "P": 0x50, "S": 0x53, "V": 0x56,
      "DOWN": 0x28, "UP": 0x26, "LEFT": 0x25, "RIGHT": 0x27, "HOME": 0x24, "END": 0x23,
      "PGDN": 0x22, "PGUP": 0x21, "SPACE": 0x20}


def _key(vk, up=False):
    inp = INPUT(type=1)
    inp.ki = KEYBDINPUT(wVk=vk, wScan=u32.MapVirtualKeyW(vk, 0),
                        dwFlags=(0x0002 if up else 0), time=0, dwExtraInfo=None)
    u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    time.sleep(0.02)


def type_text(text, per_char=0.03):
    for ch in text:
        for flag in (0x0004, 0x0004 | 0x0002):
            inp = INPUT(type=1)
            inp.ki = KEYBDINPUT(wVk=0, wScan=ord(ch), dwFlags=flag, time=0, dwExtraInfo=None)
            u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            time.sleep(0.012)
        time.sleep(per_char)


def press(combo):
    parts = [p.strip().upper() for p in combo.split("+")]
    mods, name = parts[:-1], parts[-1]
    for m in mods:
        _key(VK[m])
    _key(VK[name])
    _key(VK[name], up=True)
    for m in reversed(mods):
        _key(VK[m], up=True)
    time.sleep(0.05)


# ---------- window bookkeeping ----------
def _browser_pids():
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
         f"Where-Object {{ $_.CommandLine -like '*{PROFILE}*' }} | "
         "Select-Object -ExpandProperty ProcessId"],
        capture_output=True, text=True)
    return [int(x) for x in out.stdout.split() if x.strip().isdigit()]


def _main_hwnd(pid):
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, lparam):
        wpid = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and u32.IsWindowVisible(hwnd) and u32.GetWindowTextLengthW(hwnd) > 0:
            found.append(hwnd)
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


def window_rect():
    """Rect of the isolated browser's main window (screen pixels)."""
    for pid in _browser_pids():
        hwnd = _main_hwnd(pid)
        if not hwnd:
            continue
        r = RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.right - r.left < 300:
            continue
        return {"pid": pid, "hwnd": hwnd, "left": r.left, "top": r.top,
                "right": r.right, "bottom": r.bottom,
                "width": r.right - r.left, "height": r.bottom - r.top}
    return None


def focus_window(rect=None):
    rect = rect or window_rect()
    if not rect:
        return False
    hwnd = rect["hwnd"]
    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, 9)
        time.sleep(0.5)
    u32.SetForegroundWindow(hwnd)
    time.sleep(0.35)
    return True


def save_calibration(obj):
    json.dump(obj, open(CAL_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def load_calibration():
    try:
        return json.load(open(CAL_PATH, encoding="utf-8"))
    except Exception:
        return None
