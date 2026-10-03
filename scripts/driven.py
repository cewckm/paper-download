"""driven.py — window bookkeeping for the CDP-driven Edge window on port 9222.

Finds the real OS window of the driven browser (via SystemInfo.getProcessInfo) so that
genuine mouse clicks land on the page, and brings it to the foreground before clicking.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import WS  # noqa
import oswin  # noqa

u32 = ctypes.WinDLL("user32", use_last_error=True)

PORT = 9222


class RECT(ctypes.Structure):
    _fields_ = [("l", wt.LONG), ("t", wt.LONG), ("r", wt.LONG), ("b", wt.LONG)]


def browser_pid():
    """Browser process id straight from the DevTools endpoint."""
    try:
        v = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=5).read())
        ws = WS(v["webSocketDebuggerUrl"])
        info = ws.call("SystemInfo.getProcessInfo", {})
        for p in info.get("processInfo", []):
            if p.get("type") == "browser":
                return p.get("id")
    except Exception as e:
        print("browser_pid error:", e)
    return None


def main_hwnd(pid):
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, lparam):
        wpid = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and u32.IsWindowVisible(hwnd) and u32.GetWindowTextLengthW(hwnd) > 0:
            r = RECT()
            u32.GetWindowRect(hwnd, ctypes.byref(r))
            if r.r - r.l > 400:
                found.append(hwnd)
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


def rect():
    pid = browser_pid()
    if not pid:
        return None
    hwnd = main_hwnd(pid)
    if not hwnd:
        return None
    r = RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    return {"pid": pid, "hwnd": hwnd, "left": r.l, "top": r.t, "right": r.r, "bottom": r.b,
            "width": r.r - r.l, "height": r.b - r.t}


def focus():
    pid = browser_pid()
    hwnd = main_hwnd(pid) if pid else None
    if not hwnd:
        return False
    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, 9)
        time.sleep(0.4)
    u32.SetForegroundWindow(hwnd)
    u32.BringWindowToTop(hwnd)
    time.sleep(0.3)
    return True


if __name__ == "__main__":
    print("browser pid:", browser_pid())
    print("rect:", rect())
    print("focus:", focus())
