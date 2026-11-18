"""A counter you bump with a global keyboard shortcut (works while gaming).

The count is stored in config.json under "counter". Hotkeys use pynput; written
like "ctrl+alt+c", "f8" or "shift+f9".
"""
import json
import threading

from .paths import CONFIG_FILE

try:
    from pynput import keyboard
except Exception:
    keyboard = None

SPECIAL = {"ctrl", "alt", "shift", "cmd", "win", "space", "tab", "enter", "esc", "home", "end",
           "insert", "delete", "page_up", "page_down", "up", "down", "left", "right",
           "caps_lock", "num_lock", "scroll_lock", "pause", "print_screen", "menu"}


def to_pynput(hotkey):
    """'ctrl+alt+c' -> '<ctrl>+<alt>+c'; 'f8' -> '<f8>'."""
    out = []
    for part in [p.strip().lower() for p in hotkey.split("+") if p.strip()]:
        part = {"win": "cmd", "pgup": "page_up", "pgdn": "page_down", "del": "delete"}.get(part, part)
        if part in SPECIAL or (part.startswith("f") and part[1:].isdigit()):
            out.append(f"<{part}>")
        elif len(part) == 1:
            out.append(part)
        else:
            raise ValueError(f"unknown key '{part}'")
    if not out:
        raise ValueError("empty hotkey")
    return "+".join(out)


class Counter:
    def __init__(self, on_change=None):
        self.lock = threading.Lock()
        self.on_change = on_change or (lambda n: None)
        self.listener = None
        cfg = self._cfg()
        c = cfg.get("counter", {})
        self.label = c.get("label", "CHESTS")
        self.count = int(c.get("count", 0))
        self.hotkey = c.get("hotkey", "ctrl+alt+c")

    @staticmethod
    def _cfg():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save(self):
        cfg = self._cfg()
        cfg["counter"] = {"label": self.label, "count": self.count, "hotkey": self.hotkey}
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)

    def add(self, n=1):
        with self.lock:
            self.count = max(0, self.count + n)
            self.save()
        self.on_change(self.count)

    def reset(self):
        with self.lock:
            self.count = 0
            self.save()
        self.on_change(self.count)

    def listen(self, hotkey=None):
        """(Re)start the global hotkey. Returns an error message or None."""
        self.stop_listening()
        if hotkey is not None:
            self.hotkey = hotkey
            self.save()
        if keyboard is None:
            return "Hotkeys need the pynput package."
        if not self.hotkey.strip():
            return None
        try:
            combo = to_pynput(self.hotkey)
        except ValueError as e:
            return f"Hotkey: {e}"
        self.listener = keyboard.GlobalHotKeys({combo: lambda: self.add(1)})
        self.listener.daemon = True
        self.listener.start()
        return None

    def stop_listening(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
