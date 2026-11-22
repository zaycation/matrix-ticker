"""Full-color scrolling ticker engine, shared by main.py (--style scroll) and gui.py.

Settings are read live: speed and brightness apply on the next frame, padding and
leagues on the next league. Stop with stop_event.set().
"""
import json
import math
import os
import threading
import time
from dataclasses import dataclass, field

from . import render, scores, screens, style, weather

from .paths import RESTORE_FILE
MIN_GAP = 0.15          # the panel needs > 0.05 s after each frame; 0.15 s is proven
STATE_ORDER = {"in": 0, "post": 1, "pre": 2}
WEATHER, NOWPLAYING = "WEATHER", "NOW PLAYING"
DASHBOARD, CALENDAR, COUNTER = "DASHBOARD", "CALENDAR", "COUNTER"
SCREENS = [DASHBOARD, CALENDAR, COUNTER]            # static screens, shown for screen_seconds
ITEMS = list(scores.ALL) + [WEATHER, NOWPLAYING] + SCREENS   # everything the ticker can cycle
FLASH_SECONDS = 3.0


@dataclass
class Settings:
    speed: float = 24.0            # pixels per second
    padding: int = 5               # spaces between games
    brightness: int = 100          # percent
    leagues: list = field(default_factory=lambda: list(ITEMS))
    location: str = ""             # weather: city, ZIP, "91367, US" or "lat,lon"
    units: str = "F"               # weather: F or C
    weather_mode: str = "daily"    # weather: "daily" (days ahead) or "hourly" (hours ahead)
    weather_count: int = 5         # how many days / hours to show
    screen_seconds: float = 10.0   # how long each static screen (dashboard, calendar, counter) stays
    clock_24h: bool = False
    cpu_meter: str = "load"        # dashboard top meter: load, ram
    gpu_meter: str = "temp"        # dashboard bottom meter: temp, load, vram, power, fan
    loop: bool = True
    verbose: bool = False
    step: int = 4                  # pixels moved per frame
    league_gap: float = 3.0        # seconds between leagues


def short_detail(g):
    d = g["detail"].upper()
    if g["state"] == "post":
        return "F" if d == "FINAL" else d.replace("FINAL", "F")        # "F", "F/OT"
    if g["state"] == "in" and " - " in d:
        clock, period = d.split(" - ", 1)                               # "15:00 - 4TH"
        return f"{period} {clock}"
    return d


def league_strip(league, games, padding):
    games = sorted(games, key=lambda g: STATE_ORDER.get(g["state"], 3))
    segs = style.league_segments(league, games)
    for i, g in enumerate(games):
        if i:
            segs.append((" " * padding, style.WHITE))
        segs += style.game_segments(g, short_detail)
    return render.strip(segs)


def dim(buf, brightness):
    if brightness >= 100:
        return buf
    k = max(0, brightness) / 100
    return bytes(int(b * k) for b in buf)


def restore_layout(panel):
    try:
        with open(RESTORE_FILE) as f:
            pkts = [bytes.fromhex(h) for h in json.load(f)["packets"]]
    except (OSError, ValueError, KeyError):
        return "No saved layout (layouts/default.json); panel keeps the last frame."
    return "Restored your NexLinq layout." if panel.replay(pkts) else "Restore sent, but no echo."


class ScrollTicker:
    def __init__(self, panel, settings, log=print, stop_event=None, games_source=None, show=None,
                 counter=None):
        """panel: matrix.transport.Matrix (or None with show= for previews).
        games_source(league) -> list of games; defaults to live ESPN data.
        counter: matrix.counter.Counter for the COUNTER screen and its flash."""
        self.panel, self.s, self.log = panel, settings, log
        self.stop = stop_event or threading.Event()
        self.flash = threading.Event()        # set when the counter is bumped
        self.counter = counter
        self.games_source = games_source or scores.games
        self.show = show or self._send

    def _wait(self, seconds):
        """Sleep in short steps: Event.wait() can't be interrupted by Ctrl+C on Windows,
        time.sleep() can. Stops early if stop is set."""
        end = time.perf_counter() + max(0.0, seconds)
        while not self.stop.is_set() and not self.flash.is_set():
            left = end - time.perf_counter()
            if left <= 0:
                return
            time.sleep(min(0.1, left))

    def _send(self, buf):
        ok, msg = self.panel.show_bitmap(buf)
        if not ok:
            raise RuntimeError(f"Image upload failed: {msg}. Is NexLinq still running?")

    def _frame(self, buf):
        """Send one frame (with brightness applied); returns how long it took."""
        t0 = time.perf_counter()
        self.show(dim(buf, self.s.brightness))
        return time.perf_counter() - t0

    def _maybe_flash(self):
        """If the counter was just bumped, cut in and show it for a few seconds."""
        if not self.flash.is_set() or self.counter is None:
            self.flash.clear()
            return
        self.flash.clear()
        end, blink = time.perf_counter() + FLASH_SECONDS, False
        while time.perf_counter() < end and not self.stop.is_set():
            took = self._frame(screens.counter(self.counter.label, self.counter.count, flash=True, blink=blink))
            blink = not blink
            if self.flash.is_set():            # bumped again: restart the timer
                self.flash.clear()
                end = time.perf_counter() + FLASH_SECONDS
            self._wait(max(MIN_GAP, 0.5 - took))

    def _screen(self, item):
        """Show a static screen for screen_seconds, redrawing about once a second."""
        if item == COUNTER and self.counter is None:
            return False
        self.log(item.title())
        end = time.perf_counter() + self.s.screen_seconds
        while time.perf_counter() < end and not self.stop.is_set():
            self._maybe_flash()
            if item == DASHBOARD:
                buf = screens.dashboard(h24=self.s.clock_24h, cpu_meter=self.s.cpu_meter, gpu_meter=self.s.gpu_meter)
            elif item == CALENDAR:
                buf = screens.calendar()
            else:
                buf = screens.counter(self.counter.label, self.counter.count)
            took = self._frame(buf)
            self._wait(max(MIN_GAP, 1.0 - took))
        return True

    def _strip(self, item):
        """Pixel strip for one cycle item, or None to skip it."""
        if item == NOWPLAYING:
            segs = screens.now_playing_segments()
            if not segs:
                if self.s.verbose:
                    self.log("Now playing: nothing playing" + ("" if screens.media.available()
                                                               else " (needs Windows media support)"))
                return None
            cols = render.strip(segs)
            self.log("Now playing" + (f", {len(cols)} px" if self.s.verbose else ""))
            return cols
        if item == WEATHER:
            if not self.s.location.strip():
                if self.s.verbose:
                    self.log("Weather: no location set, skipping.")
                return None
            try:
                segs = weather.segments(self.s.location, self.s.units, self.s.weather_mode, self.s.weather_count)
            except Exception as e:
                self.log(f"Weather: {e}")
                return None
            cols = render.strip(segs)
            self.log(f"Weather: {segs[0][0].title()}" + (f", {len(cols)} px" if self.s.verbose else ""))
            return cols
        try:
            games = self.games_source(item)
        except Exception as e:  # network hiccup: skip this league this cycle
            self.log(f"{item}: couldn't fetch scores ({e})")
            return None
        if not games:
            if self.s.verbose:
                self.log(f"{item}: no games today")
            return None
        cols = league_strip(item, games, self.s.padding)
        self.log(f"{item}: {len(games)} game{'s' if len(games) != 1 else ''}"
                 + (f", {len(cols)} px" if self.s.verbose else ""))
        return cols

    def run(self):
        while not self.stop.is_set():
            shown_any = False
            for item in list(self.s.leagues):
                if self.stop.is_set():
                    return
                if item in SCREENS:
                    shown_any |= self._screen(item)
                    continue
                cols = self._strip(item)
                if cols is None:
                    continue
                shown_any = True
                offset = -render.W
                while offset <= len(cols):
                    if self.stop.is_set():
                        return
                    self._maybe_flash()
                    upload = self._frame(render.frame(cols, offset))
                    # If the speed asks for more than step px per achievable frame, move further per frame.
                    speed = max(1.0, self.s.speed)
                    step = max(self.s.step, math.ceil(speed * (upload + MIN_GAP)))
                    self._wait(max(MIN_GAP, step / speed - upload))
                    offset += step
                self._wait(self.s.league_gap)
                self._maybe_flash()
            if not self.s.loop:
                return
            if not shown_any:
                self.log("Nothing to show right now in the selected items; checking again in 60 s.")
                self._wait(60)
                self._maybe_flash()
