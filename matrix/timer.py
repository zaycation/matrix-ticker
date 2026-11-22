"""Countdown timer for the panel (pomodoro, laundry, "back in 10").

While it runs (or is paused) the panel shows the timer instead of the ticker; when it hits
zero the panel flashes TIME'S UP and the ticker carries on. Start/pause from the app or a
global shortcut (default ctrl+alt+t). Settings are stored in config.json under "timer".
"""
import json
import threading
import time

from .counter import keyboard, to_pynput
from .paths import CONFIG_FILE


class Timer:
    def __init__(self, on_change=None):
        self.lock = threading.Lock()
        self.on_change = on_change or (lambda: None)
        self.listener = None
        c = self._cfg().get("timer", {})
        self.label = c.get("label", "TIMER")
        self.minutes = float(c.get("minutes", 25))
        self.hotkey = c.get("hotkey", "ctrl+alt+t")
        self._end = None                 # monotonic end time while running
        self._left = None                # seconds left while paused
        self._finished = threading.Event()

    @staticmethod
    def _cfg():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save(self):
        cfg = self._cfg()
        cfg["timer"] = {"label": self.label, "minutes": self.minutes, "hotkey": self.hotkey}
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)

    # ---- state ----
    @property
    def duration(self):
        return max(1, round(self.minutes * 60))

    def running(self):
        return self._end is not None

    def paused(self):
        return self._end is None and self._left is not None

    def active(self):
        """Running or paused: the panel shows the timer."""
        self._tick()
        return self._end is not None or self._left is not None

    def remaining(self):
        self._tick()
        with self.lock:
            if self._end is not None:
                return max(0.0, self._end - time.monotonic())
            return self._left if self._left is not None else float(self.duration)

    def progress(self):
        """Fraction of the time left, 1.0 -> 0.0."""
        return self.remaining() / self.duration

    def _tick(self):
        with self.lock:
            done = self._end is not None and time.monotonic() >= self._end
            if done:
                self._end, self._left = None, None
        if done:
            self._finished.set()
            self.on_change()

    def take_finished(self):
        """True once after the timer reaches zero."""
        self._tick()
        if self._finished.is_set():
            self._finished.clear()
            return True
        return False

    # ---- controls ----
    def start(self, minutes=None):
        with self.lock:
            if minutes is not None:
                self.minutes = float(minutes)
            left = self._left if self._left is not None else self.duration
            self._end, self._left = time.monotonic() + left, None
        self.on_change()

    def pause(self):
        with self.lock:
            if self._end is not None:
                self._left, self._end = max(0.0, self._end - time.monotonic()), None
        self.on_change()

    def toggle(self):
        """Start, pause, or resume."""
        self.pause() if self.running() else self.start()

    def reset(self):
        with self.lock:
            self._end, self._left = None, None
            self._finished.clear()
        self.on_change()

    def add_minutes(self, n):
        """Extend (or shorten) a running or paused timer."""
        with self.lock:
            if self._end is not None:
                self._end += n * 60
            elif self._left is not None:
                self._left = max(1.0, self._left + n * 60)
        self.on_change()

    # ---- hotkey ----
    def listen(self, hotkey=None):
        """(Re)start the global start/pause shortcut. Returns an error message or None."""
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
            return f"Timer hotkey: {e}"
        self.listener = keyboard.GlobalHotKeys({combo: self.toggle})
        self.listener.daemon = True
        self.listener.start()
        return None

    def stop_listening(self):
        if self.listener:
            self.listener.stop()
            self.listener = None


def clock(seconds):
    """'25:00', '4:05', '1:02:03'."""
    s = int(-(-seconds // 1))          # round up so it shows 0:01 until it really ends
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
