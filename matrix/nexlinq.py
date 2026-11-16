"""Find, quit and launch Phanteks NexLinq (Windows).

The image ticker can't run while NexLinq is open: NexLinq answers our image
uploads with its own. Quitting remembers NexLinq's .exe path in config.json
so it can be relaunched later.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT, "config.json")
NAME_MATCH = "nexlinq|phanteks"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _ps(command):
    res = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                         capture_output=True, text=True, creationflags=NO_WINDOW)
    return res.stdout.strip()


def running():
    """[(name, pid, exe_path)] of NexLinq processes."""
    out = _ps(f"Get-Process | Where-Object {{ $_.ProcessName -match '{NAME_MATCH}' }} | "
              "ForEach-Object { \"$($_.ProcessName)|$($_.Id)|$($_.Path)\" }")
    procs = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) == 3 and parts[1].isdigit():
            procs.append((parts[0], int(parts[1]), parts[2]))
    return procs


def _config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def saved_path():
    p = _config().get("nexlinq_path")
    return p if p and os.path.exists(p) else None


def save_path(path):
    cfg = _config()
    cfg["nexlinq_path"] = path
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def quit_nexlinq():
    procs = running()
    if not procs:
        return "NexLinq isn't running."
    exe = next((p for _, _, p in procs if p.lower().endswith(".exe")), None)
    if exe:
        save_path(exe)
    ids = ",".join(str(pid) for _, pid, _ in procs)
    _ps(f"Stop-Process -Id {ids} -Force -ErrorAction SilentlyContinue")
    left = running()
    if left:
        return "Couldn't close NexLinq (try running this as Administrator)."
    return "Closed NexLinq."


def launch_nexlinq(path=None):
    if running():
        return "NexLinq is already running."
    path = path or saved_path()
    if not path:
        return None          # caller should ask the user where NexLinq.exe is
    subprocess.Popen([path], cwd=os.path.dirname(path), creationflags=NO_WINDOW)
    save_path(path)
    return "Launched NexLinq."
