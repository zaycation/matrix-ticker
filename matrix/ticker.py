"""Full-color scrolling ticker engine, shared by main.py (--style scroll) and gui.py.

Settings are read live: speed and brightness apply on the next frame, padding and
leagues on the next league. Stop with stop_event.set().
"""
import json
import math
import os
import queue
import threading
import time
from dataclasses import dataclass, field

from . import alerts, favorites, meetings, quakes, render, scores, screens, sleeper, style, weather
from .font import ICON_CHAR

from .paths import RESTORE_FILE
MIN_GAP = 0.15          # the panel needs > 0.05 s after each frame; 0.15 s is proven
STATE_ORDER = {"in": 0, "post": 1, "pre": 2}
WEATHER, NOWPLAYING, FANTASY, MEETINGS = "WEATHER", "NOW PLAYING", "FANTASY", "MEETINGS"
DASHBOARD, CALENDAR, COUNTER, TIMER = "DASHBOARD", "CALENDAR", "COUNTER", "TIMER"
SCREENS = [DASHBOARD, CALENDAR, COUNTER, TIMER]            # static screens, shown for screen_seconds
ITEMS = list(scores.ALL) + [FANTASY, MEETINGS, WEATHER, NOWPLAYING] + SCREENS   # everything the ticker can cycle
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
    favorites: str = ""            # favorite teams, e.g. "Bears, Sparks" (see matrix/favorites.py)
    favorites_only: bool = False   # sports: show only games with a favorite team
    alerts: bool = True            # flash big moments for favorite teams (and fantasy big plays)
    sleeper_user: str = ""         # Sleeper username for FANTASY
    sleeper_league: str = ""       # only leagues whose name contains this ("" = all your leagues)
    calendar_url: str = ""         # private iCal link for MEETINGS (see matrix/meetings.py)
    meeting_window: int = 90       # show meetings starting within this many minutes
    meeting_alert: int = 5         # reminder this many minutes before (0 = off)
    quake_alerts: bool = True      # earthquake cut-ins near the weather location
    quake_radius: int = 50         # miles
    keep_awake: bool = True        # hold off automatic Windows sleep while running (monitors may still turn off)
    cpu_meter: str = "load"        # dashboard top meter: load, ram
    dashboard_corner: str = "both" # dashboard top-right: "date", "ping", or "both" (taking turns)
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


def league_strip(league, games, padding, terms=()):
    """terms: favorite-team terms; their games go first, marked with a gold star."""
    games = sorted(games, key=lambda g: (favorites.side(g, terms) is None, STATE_ORDER.get(g["state"], 3)))
    segs = style.league_segments(league, games)
    for i, g in enumerate(games):
        if i:
            segs.append((" " * padding, style.WHITE))
        if favorites.side(g, terms):
            segs += [(ICON_CHAR["star"], None), (" ", style.WHITE)]
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
                 counter=None, timer=None):
        """panel: matrix.transport.Matrix (or None with show= for previews).
        games_source(league) -> list of games; defaults to live ESPN data.
        counter: matrix.counter.Counter for the COUNTER screen and its flash."""
        self.panel, self.s, self.log = panel, settings, log
        self.stop = stop_event or threading.Event()
        self.flash = threading.Event()        # set when the counter is bumped
        self.counter = counter
        self.timer = timer                    # matrix.timer.Timer: takes over the panel while running
        self.alert_q, self.alert_ready = queue.Queue(), threading.Event()
        self.games_source = games_source or scores.games
        self.show = show or self._send

    def _wait(self, seconds):
        """Sleep in short steps: Event.wait() can't be interrupted by Ctrl+C on Windows,
        time.sleep() can. Stops early if stop is set."""
        end = time.perf_counter() + max(0.0, seconds)
        while (not self.stop.is_set() and not self.flash.is_set() and not self.alert_ready.is_set()
               and not (self._timer_on() and (self.timer.active() or self.timer._finished.is_set()))):
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

    def push_alert(self, alert):
        """Queue a big-moment alert; it cuts in at the next frame (thread-safe)."""
        self.alert_q.put(alert)
        self.alert_ready.set()

    def _show_alert(self, alert):
        self.log("Alert: " + alert.text())
        if alert.scroll:
            self._scroll(render.strip(alert.scroll), interruptible=False)
            return
        word, score = alerts.frames(alert)
        for i in range(6):                     # event, score, event, ... about 5 seconds
            if self.stop.is_set():
                return
            took = self._frame(word if i % 2 == 0 else score)
            end = time.perf_counter() + max(MIN_GAP, 0.85 - took)
            while time.perf_counter() < end and not self.stop.is_set():
                time.sleep(0.05)

    def _timer_on(self):
        """The timer only shows when TIMER is ticked."""
        return self.timer is not None and TIMER in self.s.leagues

    def _timer_takeover(self):
        """While the timer runs (or is paused) show it full-time; flash TIME'S UP at zero."""
        if not self._timer_on():
            return
        t = self.timer
        if t.active():
            self.log(f"Timer: {t.label}")
            blink = False
            while t.active() and self._timer_on() and not self.stop.is_set():
                took = self._frame(screens.timer(t.label, t.remaining(), t.progress(), t.paused(), blink))
                blink = not blink
                if self.alert_ready.is_set() or self.flash.is_set():
                    self._maybe_flash(timer=False)
                end = time.perf_counter() + max(MIN_GAP, 0.5 - took)
                while time.perf_counter() < end and not self.stop.is_set() and not self.alert_ready.is_set():
                    time.sleep(0.05)
        if t.take_finished():
            self.log("Timer: time's up")
            end, blink = time.perf_counter() + 8, True
            while time.perf_counter() < end and not self.stop.is_set() and not t.active():
                took = self._frame(screens.times_up(t.label, blink))
                blink = not blink
                time.sleep(max(MIN_GAP, 0.5 - took))

    def _maybe_flash(self, timer=True):
        """Cut in for the timer, alerts, and the counter if it was just bumped."""
        if timer:
            self._timer_takeover()
        if self.alert_ready.is_set():
            self.alert_ready.clear()
            while not self.alert_q.empty() and not self.stop.is_set():
                self._show_alert(self.alert_q.get())
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
        if self.stop.is_set():
            return False
        if item == COUNTER and self.counter is None:
            return False
        if item == TIMER:
            return False             # the timer cuts in on its own while it runs
        self.log(item.title())
        end = time.perf_counter() + self.s.screen_seconds
        while time.perf_counter() < end and not self.stop.is_set():
            self._maybe_flash()
            if self.stop.is_set():
                break
            if item == DASHBOARD:
                buf = screens.dashboard(h24=self.s.clock_24h, cpu_meter=self.s.cpu_meter, gpu_meter=self.s.gpu_meter,
                                        corner=self.s.dashboard_corner)
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
        if item == MEETINGS:
            if not self.s.calendar_url.strip():
                if self.s.verbose:
                    self.log("Meetings: no calendar link set, skipping.")
                return None
            try:
                segs = meetings.segments(self.s.calendar_url, self.s.meeting_window, self.s.clock_24h)
            except Exception as e:
                self.log(f"Meetings: couldn't read the calendar ({e})")
                return None
            if not segs:
                if self.s.verbose:
                    self.log(f"Meetings: nothing in the next {self.s.meeting_window} min")
                return None
            cols = render.strip(segs)
            self.log("Meetings" + (f", {len(cols)} px" if self.s.verbose else ""))
            return cols
        if item == FANTASY:
            if not self.s.sleeper_user.strip():
                if self.s.verbose:
                    self.log("Fantasy: no Sleeper username set, skipping.")
                return None
            try:
                segs = sleeper.segments(self.s.sleeper_user, self.s.sleeper_league)
            except Exception as e:
                self.log(f"Fantasy: {e}")
                return None
            if not segs:
                if self.s.verbose:
                    self.log("Fantasy: no matchup this week")
                return None
            cols = render.strip(segs)
            self.log("Fantasy" + (f", {len(cols)} px" if self.s.verbose else ""))
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
        terms = favorites.parse(self.s.favorites)
        if self.s.favorites_only and terms:
            games = [g for g in games if favorites.side(g, terms)]
        if not games:
            if self.s.verbose:
                self.log(f"{item}: no {'favorite-team ' if self.s.favorites_only and terms else ''}games today")
            return None
        cols = league_strip(item, games, self.s.padding, terms)
        self.log(f"{item}: {len(games)} game{'s' if len(games) != 1 else ''}"
                 + (f", {len(cols)} px" if self.s.verbose else ""))
        return cols

    def _scroll(self, cols, interruptible=True):
        """Scroll a strip across once. interruptible: alerts and the counter may cut in
        (not while showing an alert itself). Returns False if stopped."""
        offset = -render.W
        while offset <= len(cols):
            if self.stop.is_set():
                return False
            if interruptible:
                self._maybe_flash()
            upload = self._frame(render.frame(cols, offset))
            # If the speed asks for more than step px per achievable frame, move further per frame.
            speed = max(1.0, self.s.speed)
            step = max(self.s.step, math.ceil(speed * (upload + MIN_GAP)))
            pause = max(MIN_GAP, step / speed - upload)
            if interruptible:
                self._wait(pause)
            else:
                end = time.perf_counter() + pause
                while time.perf_counter() < end and not self.stop.is_set():
                    time.sleep(0.02)
            offset += step
        return True

    def run(self):
        quakes.Watcher(self.s, self.push_alert, self.stop, self.log).start()
        alerts.Watcher(self.s, self.push_alert, self.stop, self.games_source, self.log).start()
        sleeper.Watcher(self.s, self.push_alert, self.stop, self.log).start()
        meetings.Watcher(self.s, self.push_alert, self.stop, self.log).start()
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
                if not self._scroll(cols):
                    return
                self._wait(self.s.league_gap)
                self._maybe_flash()
            if not self.s.loop:
                return
            if not shown_any:
                self.log("Nothing to show right now in the selected items; checking again in 60 s.")
                self._wait(60)
                self._maybe_flash()
