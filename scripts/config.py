"""config.py — one place that resolves every path/port this skill uses.

Resolution order (first hit wins):
  1. environment variables   PAPER_* / the values below
  2. config.json beside this file (written by launch.py)
  3. built-in defaults

Defaults target this machine: Edge on Windows, the bundled DSH python, and the
user's literature folder.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "config.json")

DEFAULTS = {
    "profileDir": r"C:\Users\32464\Desktop\skill-dsh\paper-download\edge-profile",
    "downloadDir": r"C:\Users\32464\Desktop\wenxian\paper\test",
    "workDir": r"C:\Users\32464\Desktop\wenxian\_tools",
    "browserExe": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "browserExeAlt": r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "port": 9222,
    "python": r"C:\Users\32464\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe",
    "excludeJournals": ["Physical Review B", "Physical Review Materials", "Applied Physics Letters"],
    "minImpactFactor": 5.0,
}


def _read_file():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load():
    cfg = dict(DEFAULTS)
    cfg.update(_read_file())
    env_map = {
        "PAPER_DOWNLOAD_DIR": "downloadDir",
        "PAPER_WORK_DIR": "workDir",
        "PAPER_PROFILE_DIR": "profileDir",
        "PAPER_BROWSER": "browserExe",
        "PAPER_PORT": "port",
        "PAPER_PYTHON": "python",
    }
    for env, key in env_map.items():
        if os.environ.get(env):
            cfg[key] = int(os.environ[env]) if key == "port" else os.environ[env]
    if not os.path.exists(cfg["browserExe"]) and os.path.exists(cfg["browserExeAlt"]):
        cfg["browserExe"] = cfg["browserExeAlt"]
    cfg["scriptsDir"] = HERE
    cfg["xmolResults"] = os.path.join(cfg["workDir"], "xmol_results.json")
    cfg["statusFile"] = os.path.join(cfg["workDir"], "download_status.json")
    cfg["calibration"] = os.path.join(HERE, "osclick-cal.json")
    return cfg


def save(cfg, patch=None):
    data = _read_file()
    for key in ("profileDir", "downloadDir", "workDir", "browserExe", "port", "python",
                "excludeJournals", "minImpactFactor"):
        if key in cfg:
            data[key] = cfg[key]
    if patch:
        data.update(patch)
    os.makedirs(HERE, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def describe(cfg):
    return {
        "browserExe": cfg["browserExe"],
        "browserExists": os.path.exists(cfg["browserExe"]),
        "profileDir": cfg["profileDir"],
        "downloadDir": cfg["downloadDir"],
        "downloadDirExists": os.path.isdir(cfg["downloadDir"]),
        "workDir": cfg["workDir"],
        "port": cfg["port"],
        "python": cfg["python"],
    }


if __name__ == "__main__":
    cfg = load()
    print(json.dumps(describe(cfg), ensure_ascii=False, indent=2))
    print("config file:", CONFIG_FILE, "exists:", os.path.exists(CONFIG_FILE))
    sys.exit(0)
