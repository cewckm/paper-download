"""launch.py — start the driven browser window this skill controls.

Why a dedicated profile: Chromium refuses to open a DevTools port for the *default* profile,
and a second instance cannot attach to an already-running one. So the skill owns a profile dir
and always launches with `--remote-debugging-port`.

PDF handling is pre-configured so that "Download PDF" clicks actually write files instead of
opening the built-in viewer (that mismatch is the single most common failure).

    python launch.py            # start (or report it is already up)
    python launch.py --status   # only report
    python launch.py --force    # close and restart the driven window
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa

CFG = config.load()


def probe(port=None, timeout=4):
    port = port or CFG["port"]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def kill_driven():
    """Stop only the browser that uses our own profile dir (never the user's own browser)."""
    prof = CFG["profileDir"]
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
          f"Where-Object {{ $_.CommandLine -like '*{prof}*' }} | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)


def write_pdf_prefs():
    """Force PDFs to download instead of opening in the viewer, and set the download dir."""
    prof, dest = CFG["profileDir"], CFG["downloadDir"]
    default = os.path.join(prof, "Default")
    os.makedirs(default, exist_ok=True)
    os.makedirs(dest, exist_ok=True)
    prefs_path = os.path.join(default, "Preferences")
    data = {}
    if os.path.exists(prefs_path):
        try:
            with open(prefs_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data.setdefault("plugins", {})["always_open_pdf_externally"] = True
    data.setdefault("download", {})["prompt_for_download"] = False
    data["download"]["default_directory"] = dest
    with open(prefs_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return prefs_path


def launch():
    info = probe()
    if "error" not in info:
        print(f"[paper] debug port {CFG['port']} already answering: {info.get('Browser')}")
        return True
    if not os.path.exists(CFG["browserExe"]):
        print(f"[paper] browser not found: {CFG['browserExe']}")
        return False
    prefs = write_pdf_prefs()
    print(f"[paper] pdf prefs -> {prefs}")
    args = [
        CFG["browserExe"],
        f"--remote-debugging-port={CFG['port']}",
        "--remote-allow-origins=*",
        f"--user-data-dir={CFG['profileDir']}",
        "--no-first-run", "--no-default-browser-check",
        "--window-size=1500,1000", "--window-position=40,20",
        "about:blank",
    ]
    subprocess.Popen(args, close_fds=True)
    for i in range(30):
        time.sleep(1.5)
        info = probe()
        if "error" not in info:
            print(f"[paper] window up after {int((i + 1) * 1.5)}s: {info.get('Browser')}")
            config.save(CFG)
            return True
    print("[paper] window did not expose its debug port in 45s")
    return False


def main():
    args = sys.argv[1:]
    if "--status" in args:
        info = probe()
        up = "error" not in info
        print(json.dumps({"up": up, "port": CFG["port"], "browser": info.get("Browser"),
                          "error": info.get("error"), "config": config.describe(CFG)},
                         ensure_ascii=False, indent=2))
        return 0 if up else 1
    if "--force" in args:
        kill_driven()
        time.sleep(3)
    ok = launch()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
