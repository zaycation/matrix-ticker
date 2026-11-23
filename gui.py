"""Matrix Ticker control window. Modern dark look (customtkinter), see-through if you like.

    pythonw gui.py           # no console window
    pythonw gui.py --tray    # start hidden in the system tray (used at Windows startup)

Closing the window keeps it running in the system tray (needs pystray + Pillow).
Settings are saved to config.json under "gui".
"""
import ctypes
import dataclasses
import json
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog

import customtkinter as ctk

from matrix import autostart, messages, nexlinq, power, updates
from matrix.counter import Counter
from matrix.timer import Timer, clock
from matrix.ticker import COUNTER, FANTASY, ITEMS, MEETINGS, MESSAGES, TIMER, ScrollTicker, Settings, restore_layout
from matrix.version import __version__

try:
    import pystray
    from matrix.icon import make_image
except Exception:          # tray is optional when running from source
    pystray = None

from matrix.paths import CONFIG_FILE

BG, CARD, FIELD, FG, MUTED = "#121418", "#1c1f26", "#272b34", "#e8eaee", "#8b919c"
ACCENT, ACCENT_HI = "#6b8cff", "#8aa4ff"
BUTTON, BUTTON_HI = "#2c313b", "#383e4a"
GREEN, GREEN_HI, RED, RED_HI = "#1f9d55", "#25b864", "#c0392b", "#d9443a"
GOLD = "#ffc800"
FAMILY = "Segoe UI"
DEFAULT_OPACITY = 95

ctk.set_appearance_mode("dark")


def load_cfg():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def led_icon(size=32):
    """Small dark tile with a few colored 'LEDs', drawn in code (no image files)."""
    img = tk.PhotoImage(width=size, height=size)
    img.put(CARD, to=(0, 0, size, size))
    colors = ["#ff3b3b", "#ffffff", "#25b864", "#6b8cff", "#ffc72c"]
    cell = size // 6
    for row in range(2, 4):
        for col in range(1, 5):
            c = colors[(row * 4 + col) % len(colors)]
            x, y = col * cell + 1, row * cell + 1
            img.put(c, to=(x, y, x + cell - 2, y + cell - 2))
    return img


def font(size=13, weight="normal"):
    return ctk.CTkFont(family=FAMILY, size=size, weight=weight)


class App:
    SLIDERS = [  # attr, label, low, high, step, cast
        ("speed", "Speed", 6, 48, 3, float),
        ("padding", "Padding", 1, 15, 1, int),
        ("brightness", "Brightness", 10, 100, 10, int),
        ("screen_seconds", "Screen time", 2, 30, 2, int),
    ]
    UNITS = {"speed": " px/s", "padding": "", "brightness": "%", "screen_seconds": "s"}
    WMODES = {"days": "daily", "hours": "hourly"}
    WMODES_REV = {v: k for k, v in WMODES.items()}
    COUNTS = {"daily": range(1, 15), "hourly": range(1, 25)}    # Open-Meteo gives 16 days ahead
    CPU_METERS = {"Load": "load", "Busiest core": "peak", "RAM": "ram"}
    CORNERS = {"Date + ping": "both", "Date": "date", "Ping": "ping"}
    REMIND = {"Off": 0, "2 min before": 2, "5 min before": 5, "10 min before": 10, "15 min before": 15}
    REMIND_REV = {v: k for k, v in REMIND.items()}
    GPU_METERS = {"Temperature": "temp", "Load": "load", "VRAM": "vram", "Power": "power", "Fan": "fan"}

    def __init__(self, root):
        self.root = root
        self.settings = Settings(verbose=True)
        self.thread, self.stop_event = None, threading.Event()
        self.logq, self._save_job = queue.Queue(), None

        saved = load_cfg().get("gui", {})
        for key in ("speed", "padding", "brightness", "loop", "location", "units", "weather_mode",
                    "weather_count", "screen_seconds", "clock_24h", "cpu_meter", "gpu_meter",
                    "favorites", "favorites_only", "alerts", "sleeper_user", "sleeper_league", "keep_awake", "calendar_url", "meeting_window",
                    "meeting_alert", "message_topic", "quake_alerts", "quake_radius", "dashboard_corner"):
            if key in saved:
                setattr(self.settings, key, saved[key])
        if "leagues" in saved:
            self.settings.leagues = [lg for lg in ITEMS if lg in saved["leagues"]]
        self.cmdq, self.tray, self._told_tray, self._closed = queue.Queue(), None, False, False
        self.ticker = None
        self.counter = Counter(on_change=self._counter_bumped)
        self.timer = Timer()

        root.title("Matrix Ticker")
        root.configure(fg_color=BG)
        root.resizable(False, False)
        self.icon = led_icon()
        root.iconphoto(True, self.icon)
        root.after(300, lambda: root.iconphoto(True, self.icon))   # customtkinter sets its own at ~200 ms

        outer = ctk.CTkFrame(root, fg_color="transparent")
        outer.pack(padx=16, pady=14)

        # header
        head = ctk.CTkFrame(outer, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(head, text="Matrix Ticker", text_color=FG, font=font(20, "bold")).pack(side="left")
        self.status = ctk.CTkLabel(head, text="●  Stopped", text_color=MUTED, font=font(12),
                                   fg_color=CARD, corner_radius=12, padx=10, height=26)
        self.status.pack(side="right")

        # update banner (hidden until a newer release is found)
        self.update_bar = ctk.CTkFrame(outer, fg_color="#1d3a2a", corner_radius=10)
        self.update_text = ctk.CTkLabel(self.update_bar, text="", text_color=FG, font=font(12))
        self.update_text.pack(side="left", padx=12, pady=6)
        self._update_url = updates.RELEASES_PAGE
        ctk.CTkButton(self.update_bar, text="Download", width=90, height=28, corner_radius=8, fg_color=GREEN,
                      hover_color=GREEN_HI, text_color="white", font=font(12),
                      command=lambda: webbrowser.open(self._update_url)).pack(side="right", padx=8, pady=6)
        self.head = head

        # big run/stop toggle
        runrow = ctk.CTkFrame(outer, fg_color="transparent")
        runrow.pack(fill="x", pady=(12, 4))
        self.toggle = ctk.CTkButton(runrow, text="▶   Run", command=self.toggle_run, height=50, corner_radius=14,
                                    fg_color=GREEN, hover_color=GREEN_HI, text_color="white",
                                    font=font(17, "bold"))
        self.toggle.pack(side="left", fill="x", expand=True)
        self.restart_btn = ctk.CTkButton(runrow, text="↻   Restart", command=self.restart, height=50, width=170,
                                         corner_radius=14, fg_color=ACCENT, hover_color=ACCENT_HI,
                                         text_color="white", font=font(17, "bold"))
        self._run_snapshot, self._restarting = None, False

        # sliders
        # two columns keep the window short enough for a 1080p screen
        cols = ctk.CTkFrame(outer, fg_color="transparent")
        cols.pack(fill="x")
        left = ctk.CTkFrame(cols, fg_color="transparent")
        left.pack(side="left", fill="y", anchor="n")
        right = ctk.CTkFrame(cols, fg_color="transparent")
        right.pack(side="left", fill="y", anchor="n", padx=(12, 0))

        box = self._card(left, "Ticker")
        self.vars = {}
        for r, (attr, label, lo, hi, step, cast) in enumerate(self.SLIDERS, start=1):
            self._slider(box, r, attr, label, lo, hi, step, cast)

        # what to show
        box2 = self._card(left, "Show")
        grid = ctk.CTkFrame(box2, fg_color="transparent")
        grid.grid(row=1, column=0, columnspan=3, sticky="w")
        self.league_vars = {}
        for i, lg in enumerate(ITEMS):
            v = tk.BooleanVar(value=lg in self.settings.leagues)
            self._check(grid, lg, v, self._leagues_changed).grid(row=i // 4, column=i % 4, sticky="w",
                                                                 padx=(0, 12), pady=3)
            self.league_vars[lg] = v
        fav = ctk.CTkFrame(box2, fg_color="transparent")
        fav.grid(row=2, column=0, columnspan=4, sticky="we", pady=(8, 0))
        self.favorites = ctk.CTkEntry(fav, placeholder_text="Favorite teams, e.g. Bears, Sparks", width=230,
                                      height=30, corner_radius=8, fg_color=FIELD, border_width=0, text_color=FG,
                                      placeholder_text_color=MUTED, font=font())
        if self.settings.favorites:
            self.favorites.insert(0, self.settings.favorites)
        for ev in ("<KeyRelease>", "<FocusOut>"):
            self.favorites.bind(ev, lambda e: self._favorites_changed())
        self.favorites.pack(side="left")
        self._button(fav, "Test alert", self.test_alert, width=86, height=30).pack(side="right")
        fsw = ctk.CTkFrame(box2, fg_color="transparent")
        fsw.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.fav_only = tk.BooleanVar(value=self.settings.favorites_only)
        self.alerts_on = tk.BooleanVar(value=self.settings.alerts)
        self._switch(fsw, "Only my teams", self.fav_only, self._favorites_changed).pack(side="left", padx=(0, 14))
        self._switch(fsw, "Big-moment alerts", self.alerts_on, self._favorites_changed).pack(side="left")

        # weather
        box_w = self._card(left, "Weather")
        # no textvariable: customtkinter only shows the placeholder hint without one
        self.location = ctk.CTkEntry(box_w, placeholder_text="City or ZIP, e.g. 91367", width=170, height=32,
                                     corner_radius=8, fg_color=FIELD, border_width=0, text_color=FG,
                                     placeholder_text_color=MUTED, font=font())
        if self.settings.location:
            self.location.insert(0, self.settings.location)
        self.location.bind("<KeyRelease>", lambda e: self._location_changed())
        self.location.bind("<FocusOut>", lambda e: self._location_changed())
        self.location.grid(row=1, column=0, sticky="w")
        menus = ctk.CTkFrame(box_w, fg_color="transparent")
        menus.grid(row=1, column=1, sticky="e", padx=(10, 0))
        self.units = tk.StringVar(value="°" + self.settings.units)
        self._dropdown(menus, self.units, ["°F", "°C"], 62).pack(side="left")
        self.wcount = tk.StringVar(value=str(self.settings.weather_count))
        self.count_menu = self._dropdown(menus, self.wcount, ["5"], 58)
        self.count_menu.pack(side="left", padx=(6, 0))
        self.wmode = tk.StringVar(value=self.WMODES_REV[self.settings.weather_mode])
        self._dropdown(menus, self.wmode, list(self.WMODES), 80, self._mode_changed).pack(side="left", padx=(6, 0))
        self._fill_counts()
        box_w.columnconfigure(1, weight=1)
        qrow = ctk.CTkFrame(box_w, fg_color="transparent")
        qrow.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.quake_on = tk.BooleanVar(value=self.settings.quake_alerts)
        self._switch(qrow, "Earthquake alerts within", self.quake_on, self._location_changed).pack(side="left")
        self.quake_radius = tk.StringVar(value=f"{self.settings.quake_radius} mi")
        self._dropdown(qrow, self.quake_radius, ["25 mi", "50 mi", "75 mi", "100 mi"], 84,
                       lambda _v: self._location_changed()).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(qrow, text="(M3.5+)", text_color=MUTED, font=font(11)).pack(side="left", padx=(6, 0))

        # messages (only shown when MESSAGES is ticked)
        if not self.settings.message_topic:
            self.settings.message_topic = messages.new_topic()      # a private code, made once
        self.messages_box = box_n = self._card(left, "Messages (from a phone)", pack=False)
        self.topic_link = ctk.CTkEntry(box_n, width=300, height=30, corner_radius=8, fg_color=FIELD, border_width=0,
                                       text_color=FG, font=font(12))
        self._show_topic()
        self.topic_link.grid(row=1, column=0, columnspan=2, sticky="w")
        tl = ctk.CTkFrame(box_n, fg_color="transparent")
        tl.grid(row=1, column=2, columnspan=2, sticky="e")
        self._button(tl, "Copy", self._copy_topic, width=54, height=30).pack(side="left", padx=(6, 0))
        self._button(tl, "New link", self._new_topic, width=74, height=30).pack(side="left", padx=(6, 0))
        self.msg_text = ctk.CTkEntry(box_n, placeholder_text="Send a test message", width=300, height=30,
                                     corner_radius=8, fg_color=FIELD, border_width=0, text_color=FG,
                                     placeholder_text_color=MUTED, font=font())
        self.msg_text.bind("<Return>", lambda e: self._send_message())
        self.msg_text.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ml = ctk.CTkFrame(box_n, fg_color="transparent")
        ml.grid(row=2, column=2, columnspan=2, sticky="e", pady=(6, 0))
        self._button(ml, "Send", self._send_message, width=54, height=30).pack(side="left", padx=(6, 0))
        self._button(ml, "Clear", self._clear_message, width=74, height=30).pack(side="left", padx=(6, 0))
        ctk.CTkLabel(box_n, text="Her iPhone Shortcut sends to this link (setup steps: README → Messages).",
                     text_color=MUTED, font=font(11)).grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))
        box_n.columnconfigure(1, weight=1)

        # timer (only shown when TIMER is ticked)
        self.left = left
        self.timer_box = box_t = self._card(left, "Timer", pack=False)
        self.timer_left = ctk.CTkLabel(box_t, text=clock(self.timer.duration), text_color=FG,
                                       font=font(26, "bold"), width=110, anchor="e")
        self.timer_left.grid(row=0, column=3, rowspan=2, sticky="ne")
        self.t_label = tk.StringVar(value=self.timer.label)
        self.t_label.trace_add("write", lambda *_: self._timer_settings())
        self._entry(box_t, self.t_label, 110).grid(row=1, column=0, sticky="w", pady=3)
        self.t_minutes = tk.StringVar(value=f"{self.timer.minutes:g}")
        ctk.CTkComboBox(box_t, variable=self.t_minutes, values=["5", "10", "15", "25", "30", "45", "60", "90"],
                        width=72, height=28, corner_radius=8, fg_color=FIELD, border_width=0, button_color=FIELD,
                        button_hover_color=BUTTON_HI, text_color=FG, font=font(), dropdown_fg_color=CARD,
                        dropdown_hover_color=BUTTON_HI, dropdown_text_color=FG, dropdown_font=font(),
                        command=lambda _v: self._timer_settings()).grid(row=1, column=1, sticky="w", padx=(8, 0))
        self.t_minutes.trace_add("write", lambda *_: self._timer_settings())
        ctk.CTkLabel(box_t, text="min", text_color=MUTED, font=font(12)).grid(row=1, column=2, sticky="w", padx=(4, 0))
        tb = ctk.CTkFrame(box_t, fg_color="transparent")
        tb.grid(row=2, column=0, columnspan=4, sticky="we", pady=(6, 0))
        self.t_start = ctk.CTkButton(tb, text="Start", command=self._timer_toggle, width=80, height=30,
                                     corner_radius=8, fg_color=GREEN, hover_color=GREEN_HI, text_color="white",
                                     font=font(12, "bold"))
        self.t_start.pack(side="left")
        self._button(tb, "Reset", self.timer.reset, width=60, height=30).pack(side="left", padx=(6, 0))
        self._button(tb, "+5 min", lambda: self.timer.add_minutes(5), width=60, height=30).pack(side="left", padx=(6, 0))
        self.t_hotkey = tk.StringVar(value=self.timer.hotkey)
        self._button(tb, "Set", self._set_timer_hotkey, width=44, height=30).pack(side="right")
        self._entry(tb, self.t_hotkey, 100).pack(side="right", padx=(0, 6))
        ctk.CTkLabel(box_t, text="Shortcut starts/pauses. While it runs, the panel shows the timer.",
                     text_color=MUTED, font=font(11)).grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))
        box_t.columnconfigure(3, weight=1)

        # options
        box_o = self._card(right, "Options")
        self.loop = tk.BooleanVar(value=self.settings.loop)
        self.autorun = tk.BooleanVar(value=saved.get("autorun", False))
        self.h24 = tk.BooleanVar(value=self.settings.clock_24h)
        self.awake = tk.BooleanVar(value=self.settings.keep_awake)
        self.on_boot = tk.BooleanVar(value=autostart.enabled())
        sw = ctk.CTkFrame(box_o, fg_color="transparent")
        sw.grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 2))
        for i, (text, var, cmd) in enumerate((("Loop", self.loop, self._opts_changed),
                                              ("24-hour clock", self.h24, self._opts_changed),
                                              ("Start ticker when app opens", self.autorun, self._schedule_save),
                                              ("Keep PC awake while running", self.awake, self._opts_changed),
                                              ("Open when Windows starts", self.on_boot, self._boot_changed))):
            self._switch(sw, text, var, cmd).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 14), pady=2)
        self.opacity = tk.IntVar(value=int(saved.get("opacity", DEFAULT_OPACITY)))
        self._row_slider(box_o, 2, "Window opacity", self.opacity, 60, 100, 5, "%", self._opacity_changed)
        meters = ctk.CTkFrame(box_o, fg_color="transparent")
        meters.grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ctk.CTkLabel(meters, text="Dashboard meters", text_color=FG, font=font(), width=110,
                     anchor="w").pack(side="left")
        rev = lambda d, v: next((k for k, x in d.items() if x == v), next(iter(d)))
        self.cpu_meter = tk.StringVar(value=rev(self.CPU_METERS, self.settings.cpu_meter))
        self.gpu_meter = tk.StringVar(value=rev(self.GPU_METERS, self.settings.gpu_meter))
        ctk.CTkLabel(meters, text="CPU", text_color=MUTED, font=font(12)).pack(side="left", padx=(8, 4))
        self._dropdown(meters, self.cpu_meter, list(self.CPU_METERS), 128, self._meters_changed).pack(side="left")
        ctk.CTkLabel(meters, text="GPU", text_color=MUTED, font=font(12)).pack(side="left", padx=(12, 4))
        self._dropdown(meters, self.gpu_meter, list(self.GPU_METERS), 128, self._meters_changed).pack(side="left")
        crow = ctk.CTkFrame(box_o, fg_color="transparent")
        crow.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ctk.CTkLabel(crow, text="Dashboard corner", text_color=FG, font=font(), width=110, anchor="w").pack(side="left")
        self.corner = tk.StringVar(value=rev(self.CORNERS, self.settings.dashboard_corner))
        self._dropdown(crow, self.corner, list(self.CORNERS), 128, self._meters_changed).pack(side="left", padx=(8, 0))

        # meetings (only shown when MEETINGS is ticked)
        self.meetings_box = box_m = self._card(right, "Meetings (calendar)", pack=False)
        self.cal_url = ctk.CTkEntry(box_m, placeholder_text="Paste your calendar's secret iCal link", width=470,
                                    height=30, corner_radius=8, fg_color=FIELD, border_width=0, text_color=FG,
                                    placeholder_text_color=MUTED, font=font(), show="")
        if self.settings.calendar_url:
            self.cal_url.insert(0, self.settings.calendar_url)
        self.cal_url.configure(show="•" if self.settings.calendar_url else "")
        for ev in ("<KeyRelease>", "<FocusOut>"):
            self.cal_url.bind(ev, lambda _e: self._meetings_changed())
        self.cal_url.grid(row=1, column=0, columnspan=4, sticky="w")
        mrow = ctk.CTkFrame(box_m, fg_color="transparent")
        mrow.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ctk.CTkLabel(mrow, text="Show meetings within", text_color=FG, font=font(12)).pack(side="left")
        self.m_window = tk.StringVar(value=f"{self.settings.meeting_window} min")
        self._dropdown(mrow, self.m_window, ["30 min", "60 min", "90 min", "120 min", "180 min"], 100,
                       lambda _v: self._meetings_changed()).pack(side="left", padx=(6, 12))
        ctk.CTkLabel(mrow, text="Reminder", text_color=FG, font=font(12)).pack(side="left")
        self.m_alert = tk.StringVar(value=self.REMIND_REV.get(self.settings.meeting_alert, "5 min before"))
        self._dropdown(mrow, self.m_alert, list(self.REMIND), 140,
                       lambda _v: self._meetings_changed()).pack(side="left", padx=(6, 0))
        ctk.CTkLabel(box_m, text="Google Calendar: Settings → your calendar → Secret address in iCal format",
                     text_color=MUTED, font=font(11)).grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # fantasy (only shown when FANTASY is ticked)
        self.fantasy_box = box_f = self._card(right, "Fantasy (Sleeper)", pack=False)
        self.sleeper_user = self._hint_entry(box_f, "Sleeper username", self.settings.sleeper_user, 160)
        self.sleeper_user.grid(row=1, column=0, sticky="w")
        self.sleeper_league = self._hint_entry(box_f, "League name (blank = all)", self.settings.sleeper_league, 200)
        self.sleeper_league.grid(row=1, column=1, sticky="w", padx=(8, 0))
        ctk.CTkLabel(box_f, text="Shows your matchup score; with alerts on, flashes starters' big plays (+3 pts).",
                     text_color=MUTED, font=font(11)).grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # counter (only shown when COUNTER is ticked)
        self.counter_box = box3 = self._card(right, "Counter", pack=False)
        self.count_label = ctk.CTkLabel(box3, text=str(self.counter.count), text_color=GOLD,
                                        font=font(26, "bold"), width=70, anchor="e")
        self.count_label.grid(row=0, column=3, rowspan=2, sticky="ne")
        ctk.CTkLabel(box3, text="Label", text_color=FG, font=font()).grid(row=1, column=0, sticky="w", pady=3)
        self.c_label = tk.StringVar(value=self.counter.label)
        self.c_label.trace_add("write", lambda *_: self._counter_label())
        self._entry(box3, self.c_label, 130).grid(row=1, column=1, sticky="w", padx=8, pady=3)
        ctk.CTkLabel(box3, text="Shortcut", text_color=FG, font=font()).grid(row=2, column=0, sticky="w", pady=3)
        self.c_hotkey = tk.StringVar(value=self.counter.hotkey)
        self._entry(box3, self.c_hotkey, 130).grid(row=2, column=1, sticky="w", padx=8, pady=3)
        self._button(box3, "Set", self._set_hotkey, width=50, height=28).grid(row=2, column=2, sticky="w")
        cb = ctk.CTkFrame(box3, fg_color="transparent")
        cb.grid(row=2, column=3, sticky="e")
        for text, cmd in (("−1", lambda: self.counter.add(-1)), ("+1", lambda: self.counter.add(1)),
                          ("Reset", self.counter.reset)):
            self._button(cb, text, cmd, width=36 if len(text) < 3 else 52, height=28).pack(side="left", padx=(4, 0))
        ctk.CTkLabel(box3, text="e.g. ctrl+alt+c or f8 (works in games)", text_color=MUTED,
                     font=font(11)).grid(row=3, column=1, columnspan=3, sticky="w", padx=8)
        box3.columnconfigure(3, weight=1)

        # bottom buttons
        self.small = small = ctk.CTkFrame(right, fg_color="transparent")
        small.pack(fill="x", pady=(10, 0))
        for i, (text, cmd) in enumerate((("Quit", self.quit), ("Reset", self.reset_defaults),
                                         ("Launch NexLinq", self.launch_nexlinq))):
            self._button(small, text, cmd, height=34).grid(row=0, column=i, sticky="ew",
                                                          padx=(0 if i == 0 else 4, 0))
            small.columnconfigure(i, weight=1, uniform="b")

        # log
        self.logbox = ctk.CTkTextbox(right, height=74, fg_color=CARD, text_color=MUTED, corner_radius=12,
                                     font=ctk.CTkFont(family="Consolas", size=12), wrap="word",
                                     state="disabled", activate_scrollbars=True)
        self.logbox.pack(fill="both", expand=True, pady=(10, 0))
        ctk.CTkLabel(outer, text=f"{'v' + __version__ if updates.parse(__version__) else 'dev'}  ·  Scores: ESPN  ·  Fantasy: Sleeper  ·  Weather: Open-Meteo.com  ·  Quakes: USGS",
                     text_color=MUTED,
                     font=font(10)).pack(anchor="e", pady=(4, 0))

        self._show_counter_box()
        self._opacity_changed()
        self._check_updates()
        for err in (self.counter.listen(), self.timer.listen()):
            if err:
                self.log(err)
        root.protocol("WM_DELETE_WINDOW", self.hide_or_quit)
        root.bind("<Unmap>", self._minimized)
        self._start_tray()
        root.after(200, self._poll)
        if self.autorun.get():
            root.after(800, self.toggle_run)

    # ---------- widgets ----------
    def _card(self, parent, title, pack=True):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=(8, 10))
        ctk.CTkLabel(inner, text=title.upper(), text_color=MUTED, font=font(11, "bold"),
                     height=18).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))
        card.inner = inner
        inner.card = card
        if pack:
            card.pack(fill="x", pady=(8, 0))
        return inner

    def _row_slider(self, parent, row, label, var, lo, hi, step, unit, on_change):
        ctk.CTkLabel(parent, text=label, text_color=FG, font=font(), width=110, anchor="w").grid(
            row=row, column=0, sticky="w")
        value = ctk.CTkLabel(parent, text="", text_color=FG, font=font(13, "bold"), width=70, anchor="e")

        def changed(_=None):
            v = round(var.get() / step) * step
            v = int(v) if float(step).is_integer() else v
            value.configure(text=f"{v}{unit}")
            on_change(v)

        steps = int(round((hi - lo) / step))
        col = ctk.CTkFrame(parent, fg_color="transparent")
        col.grid(row=row, column=1, columnspan=2, padx=8, pady=(4, 2))
        slider = ctk.CTkSlider(col, from_=lo, to=hi, number_of_steps=steps,
                               variable=var, command=changed, width=self.SLIDER_W, height=16,
                               fg_color=FIELD, progress_color=ACCENT, button_color=ACCENT,
                               button_hover_color=ACCENT_HI)
        slider.pack()
        self._notches(col, steps)
        value.grid(row=row, column=3, sticky="e")

        def wheel(e):
            var.set(min(hi, max(lo, var.get() + (step if e.delta > 0 else -step))))
            changed()
        for w in (slider, getattr(slider, "_canvas", slider)):
            w.bind("<MouseWheel>", wheel)
        value.configure(text=f"{var.get():g}{unit}")
        return changed

    SLIDER_W = 290

    def _notches(self, parent, steps):
        """Tick marks under a slider, one per stop, so it's clear it snaps."""
        scale = ctk.ScalingTracker.get_widget_scaling(parent)
        w, h = round(self.SLIDER_W * scale), round(5 * scale)
        cv = tk.Canvas(parent, width=w, height=h, bg=CARD, highlightthickness=0, bd=0)
        cv.pack()
        inset = 8 * scale                                  # the knob's centre never reaches the very ends
        for i in range(steps + 1):
            x = round(inset + (w - 2 * inset) * i / steps)
            cv.create_line(x, 0, x, h, fill="#4a505c", width=max(1, round(scale)))

    def _slider(self, parent, row, attr, label, lo, hi, step, cast):
        var = tk.DoubleVar(value=getattr(self.settings, attr))

        def apply(v):
            setattr(self.settings, attr, cast(v))
            self._schedule_save()
        changed = self._row_slider(parent, row, label, var, lo, hi, step, self.UNITS[attr], apply)
        changed()
        self.vars[attr] = (var, changed)

    def _check(self, parent, text, var, command):
        return ctk.CTkCheckBox(parent, text=text, variable=var, command=command, text_color=FG, font=font(12),
                               width=20, checkbox_width=18, checkbox_height=18, corner_radius=5, border_width=2,
                               fg_color=ACCENT, hover_color=ACCENT_HI, border_color="#4a505c")

    def _switch(self, parent, text, var, command):
        return ctk.CTkSwitch(parent, text=text, variable=var, command=command, text_color=FG, font=font(),
                             progress_color=ACCENT, button_color="#dfe3ea", button_hover_color="white",
                             fg_color=FIELD, switch_width=38, switch_height=20)

    def _dropdown(self, parent, var, choices, width, command=None):
        return ctk.CTkOptionMenu(parent, variable=var, values=choices, width=width, height=32,
                                 corner_radius=8, fg_color=FIELD, button_color=FIELD,
                                 button_hover_color=BUTTON_HI, text_color=FG, font=font(),
                                 dropdown_fg_color=CARD, dropdown_hover_color=BUTTON_HI,
                                 dropdown_text_color=FG, dropdown_font=font(),
                                 command=command or (lambda _v: self._location_changed()), dynamic_resizing=False)

    def _entry(self, parent, var, width):
        return ctk.CTkEntry(parent, textvariable=var, width=width, height=28, corner_radius=8, fg_color=FIELD,
                            border_width=0, text_color=FG, font=font())

    def _button(self, parent, text, command, **kw):
        kw.setdefault("height", 32)
        return ctk.CTkButton(parent, text=text, command=command, corner_radius=8, fg_color=BUTTON,
                             hover_color=BUTTON_HI, text_color=FG, font=font(12), **kw)

    def _fill_counts(self):
        """The number dropdown offers 1-14 days or 1-24 hours, depending on the mode."""
        counts = self.COUNTS[self.WMODES[self.wmode.get()]]
        self.count_menu.configure(values=[str(n) for n in counts])
        if int(self.wcount.get() or 5) not in counts:
            self.wcount.set(str(counts[-1]))

    def _mode_changed(self, _v=None):
        self._fill_counts()
        self._location_changed()

    def _show_counter_box(self):
        """Messages, timer, meetings, fantasy and counter settings only show when their item is ticked."""
        lefts = [(self.messages_box.card, MESSAGES), (self.timer_box.card, TIMER)]
        wanted = [c for c, item in lefts if self.league_vars[item].get()]
        if [c for c, _ in lefts if c.winfo_manager()] != wanted:
            for c, _ in lefts:
                c.pack_forget()
            for c in wanted:
                c.pack(fill="x", pady=(8, 0))
        cards = [(self.meetings_box.card, MEETINGS), (self.fantasy_box.card, FANTASY),
                 (self.counter_box.card, COUNTER)]
        wanted = [c for c, item in cards if self.league_vars[item].get()]
        if [c for c, _ in cards if c.winfo_manager()] == wanted:
            return
        for c, _ in cards:
            c.pack_forget()
        for c in wanted:
            c.pack(fill="x", pady=(8, 0), before=self.small)

    def _hint_entry(self, parent, hint, value, width):
        e = ctk.CTkEntry(parent, placeholder_text=hint, width=width, height=30, corner_radius=8, fg_color=FIELD,
                         border_width=0, text_color=FG, placeholder_text_color=MUTED, font=font())
        if value:
            e.insert(0, value)
        for ev in ("<KeyRelease>", "<FocusOut>"):
            e.bind(ev, lambda _e: self._fantasy_changed())
        return e

    def _meetings_changed(self):
        url = self.cal_url.get().strip()
        self.cal_url.configure(show="•" if url else "")     # it's a private link: keep it hidden
        self.settings.calendar_url = url
        self.settings.meeting_window = int(self.m_window.get().split()[0])
        self.settings.meeting_alert = self.REMIND[self.m_alert.get()]
        self._schedule_save()

    def _fantasy_changed(self):
        self.settings.sleeper_user = self.sleeper_user.get().strip()
        self.settings.sleeper_league = self.sleeper_league.get().strip()
        self._schedule_save()

    def _check_updates(self):
        """Ask GitHub for a newer release now and once a day (installed app only)."""
        def work():
            found = updates.check()
            if found:
                self.cmdq.put(lambda: self._show_update(*found))
        if updates.parse(__version__):
            threading.Thread(target=work, daemon=True).start()
        self.root.after(24 * 3600 * 1000, self._check_updates)

    def _show_update(self, version, url):
        self._update_url = url
        self.update_text.configure(text=f"Version {version} is available  (you have {__version__})")
        if not self.update_bar.winfo_manager():
            self.update_bar.pack(fill="x", pady=(10, 0), after=self.head)
            self.log(f"Update available: {version}. Click Download.")
            if self.tray:
                try:
                    self.tray.notify(f"Version {version} is available. Open Matrix Ticker to download it.",
                                     "Matrix Ticker update")
                except Exception:
                    pass

    def _opacity_changed(self, v=None):
        v = self.opacity.get() if v is None else v
        try:
            self.root.attributes("-alpha", max(60, min(100, int(v))) / 100)
        except tk.TclError:
            pass
        self._schedule_save()

    def _counter_bumped(self, n):
        """Called from the hotkey thread or a button: show it in the window and on the panel."""
        self.cmdq.put(lambda: self.count_label.configure(text=str(n)))
        if self.ticker is not None:
            self.ticker.flash.set()

    def _timer_settings(self):
        self.timer.label = self.t_label.get().strip() or "TIMER"
        try:
            m = float(self.t_minutes.get())
            if 0 < m <= 24 * 60:
                self.timer.minutes = m
        except ValueError:
            pass
        self.timer.save()

    def _timer_toggle(self):
        self._timer_settings()
        self.timer.toggle()
        if self.timer.running() and self.ticker is None:
            self.log("Timer started. Press Run to see it on the panel.")

    def _set_timer_hotkey(self):
        err = self.timer.listen(self.t_hotkey.get().strip())
        self.log(err or f"Timer shortcut: {self.timer.hotkey}")

    def _update_timer_view(self):
        t = self.timer
        if self.ticker is None and t.take_finished():      # not on the panel: tell the PC instead
            self.log(f"{t.label}: time's up!")
            if self.tray:
                try:
                    self.tray.notify(f"{t.label}: time's up!", "Matrix Ticker")
                except Exception:
                    pass
        self.timer_left.configure(text=clock(t.remaining()),
                                  text_color=GOLD if t.paused() else (GREEN_HI if t.running() else FG))
        want = "Pause" if t.running() else ("Resume" if t.paused() else "Start")
        if self.t_start.cget("text") != want:
            self.t_start.configure(text=want, fg_color=RED if want == "Pause" else GREEN,
                                   hover_color=RED_HI if want == "Pause" else GREEN_HI)

    def _counter_label(self):
        self.counter.label = self.c_label.get().strip() or "COUNT"
        self.counter.save()

    def _show_topic(self):
        self.topic_link.configure(state="normal")
        self.topic_link.delete(0, "end")
        self.topic_link.insert(0, messages.url(self.settings.message_topic))
        self.topic_link.configure(state="readonly")

    def _copy_topic(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(messages.url(self.settings.message_topic))
        self.log("Message link copied.")

    def _new_topic(self):
        """A fresh private link (the old one stops working; the Shortcut needs the new one)."""
        self.settings.message_topic = messages.new_topic()
        self._show_topic()
        self._schedule_save()
        self.log("New message link made. Update the Shortcut on her phone with it.")

    def _send_message(self):
        text = self.msg_text.get().strip()
        if not text:
            return
        self.msg_text.delete(0, "end")
        topic = self.settings.message_topic

        def work():
            try:
                messages.send(topic, text, "Test")
                self.log("Sent. It shows on the panel within ~10 s (MESSAGES ticked, ticker running).")
            except Exception as e:
                self.log(f"Couldn't send: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _clear_message(self):
        messages.clear()
        self.log("Message cleared from the panel.")

    def _set_hotkey(self):
        err = self.counter.listen(self.c_hotkey.get().strip())
        self.log(err or f"Counter shortcut: {self.counter.hotkey}")

    # ---------- settings ----------
    def _leagues_changed(self):
        self.settings.leagues = [lg for lg, v in self.league_vars.items() if v.get()]
        if TIMER not in self.settings.leagues and self.timer.active():
            self.timer.reset()                 # unticking TIMER also cancels a running or paused timer
            self.log("Timer cancelled.")
        self._show_counter_box()
        self._schedule_save()

    def _location_changed(self):
        self.settings.location = self.location.get().strip()
        self.settings.units = self.units.get().lstrip("°")
        self.settings.weather_mode = self.WMODES[self.wmode.get()]
        self.settings.weather_count = int(self.wcount.get() or 5)
        self.settings.quake_alerts = self.quake_on.get()
        self.settings.quake_radius = int(self.quake_radius.get().split()[0])
        self._schedule_save()

    def _favorites_changed(self):
        self.settings.favorites = self.favorites.get().strip()
        self.settings.favorites_only = self.fav_only.get()
        self.settings.alerts = self.alerts_on.get()
        self._schedule_save()

    def test_alert(self):
        """Show a made-up Bears touchdown on the panel (the ticker must be running)."""
        if self.ticker is None:
            self.log("Press Run first, then Test alert.")
            return
        from matrix import alerts
        self.ticker.push_alert(alerts.sample())

    def _meters_changed(self, _v=None):
        self.settings.cpu_meter = self.CPU_METERS[self.cpu_meter.get()]
        self.settings.gpu_meter = self.GPU_METERS[self.gpu_meter.get()]
        self.settings.dashboard_corner = self.CORNERS[self.corner.get()]
        self._schedule_save()

    def _boot_changed(self):
        err = autostart.set_enabled(self.on_boot.get())
        if err:
            self.on_boot.set(autostart.enabled())
            self.log(err)
        else:
            self.log("Opens when Windows starts (in the tray)." if self.on_boot.get()
                     else "Won't open when Windows starts.")

    def _opts_changed(self):
        self.settings.loop = self.loop.get()
        self.settings.clock_24h = self.h24.get()
        self.settings.keep_awake = self.awake.get()
        self._schedule_save()

    def _schedule_save(self):
        """Write config.json once things settle, not on every slider movement."""
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(500, self._save)

    def _save(self):
        self._save_job = None
        cfg = load_cfg()
        s = self.settings
        cfg["gui"] = {"speed": s.speed, "padding": s.padding, "brightness": s.brightness,
                      "leagues": s.leagues, "loop": s.loop,
                      "location": s.location, "units": s.units, "weather_mode": s.weather_mode,
                      "weather_count": s.weather_count,
                      "autorun": self.autorun.get(), "screen_seconds": s.screen_seconds,
                      "clock_24h": s.clock_24h, "opacity": self.opacity.get(),
                      "cpu_meter": s.cpu_meter, "gpu_meter": s.gpu_meter,
                      "favorites": s.favorites, "favorites_only": s.favorites_only, "alerts": s.alerts,
                      "sleeper_user": s.sleeper_user, "sleeper_league": s.sleeper_league,
                      "keep_awake": s.keep_awake, "calendar_url": s.calendar_url,
                      "meeting_window": s.meeting_window, "meeting_alert": s.meeting_alert,
                      "message_topic": s.message_topic,
                      "quake_alerts": s.quake_alerts, "quake_radius": s.quake_radius,
                      "dashboard_corner": s.dashboard_corner}
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)

    def reset_defaults(self):
        d = Settings()
        for attr, (var, changed) in self.vars.items():
            var.set(getattr(d, attr))
            changed()
        for lg, v in self.league_vars.items():
            v.set(lg in d.leagues)
        self.loop.set(d.loop)
        self.autorun.set(False)
        self.units.set("°" + d.units)
        self.wmode.set(self.WMODES_REV[d.weather_mode])
        self._fill_counts()
        self.wcount.set(str(d.weather_count))
        self.h24.set(False)
        self.awake.set(d.keep_awake)
        self.fav_only.set(d.favorites_only)
        self.alerts_on.set(d.alerts)
        self._favorites_changed()          # favorite teams themselves are kept
        self.quake_on.set(d.quake_alerts)
        self.quake_radius.set(f"{d.quake_radius} mi")
        self.corner.set("Date + ping")
        self.cpu_meter.set("Load")
        self.gpu_meter.set("Temperature")
        self._meters_changed()
        self.opacity.set(DEFAULT_OPACITY)
        self._opacity_changed()
        self._location_changed()
        self._leagues_changed()
        self._opts_changed()
        self.log("Settings reset to defaults.")

    # ---------- log / status ----------
    def log(self, msg):
        self.logq.put(msg)

    def _set_toggle(self, text, color, hover):
        if self.toggle.cget("text") != text:
            self.toggle.configure(text=text, fg_color=color, hover_color=hover)

    def _poll(self):
        if not self._closed:
            self._update_timer_view()
        while not self.cmdq.empty():
            self.cmdq.get()()
            if self._closed:            # a tray "Quit" just closed the window
                return
        while not self.logq.empty():
            msg = self.logq.get()
            self.logbox.configure(state="normal")
            self.logbox.insert("end", msg + "\n")
            if int(self.logbox.index("end-1c").split(".")[0]) > 300:
                self.logbox.delete("1.0", "50.0")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        running = self.thread is not None and self.thread.is_alive()
        changed = running and not self.stop_event.is_set() and self._snapshot() != self._run_snapshot
        if changed != bool(self.restart_btn.winfo_manager()):
            if changed:
                self.restart_btn.pack(side="left", padx=(8, 0))
            else:
                self.restart_btn.pack_forget()
        if not running and self._restarting:
            self._restarting = False
            self.toggle_run()
            running = True
        if running and self.stop_event.is_set() and self._restarting:
            self._set_toggle("Restarting…", "#2d3f80", "#2d3f80")
            self.status.configure(text="●  Restarting", text_color=ACCENT_HI)
        elif running and self.stop_event.is_set():
            self._set_toggle("Stopping…", "#7a2a22", "#7a2a22")
            self.status.configure(text="●  Stopping", text_color="#d9a03a")
        elif running:
            self._set_toggle("■   Stop", RED, RED_HI)
            self.status.configure(text="●  Running", text_color=GREEN_HI)
        else:
            self._set_toggle("▶   Run", GREEN, GREEN_HI)
            self.status.configure(text="●  Stopped", text_color=MUTED)
        if self.tray and getattr(self, "_tray_running", None) != running:
            self._tray_running = running
            self.tray.icon = make_image(64, running)
            self.tray.title = "Matrix Ticker: " + ("running" if running else "stopped")
            self.tray.update_menu()
        self.root.after(200, self._poll)

    # ---------- actions ----------
    def toggle_run(self):
        if self.thread and self.thread.is_alive():
            self.stop_event.set()          # the poll loop shows "Stopping…" until it's done
            return
        if not self.settings.leagues:
            self.log("Pick at least one thing to show.")
            return
        self.stop_event = threading.Event()
        self._run_snapshot = self._snapshot()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _snapshot(self):
        """Settings as they are now, to tell whether a restart would change anything."""
        return dataclasses.asdict(self.settings)

    def restart(self):
        """Stop, then start again with the current settings (the poll loop starts it)."""
        if self.thread and self.thread.is_alive():
            self._restarting = True
            self.stop_event.set()

    RECONNECT_S = 10

    def _worker(self):
        """Run the ticker; if the display drops out (e.g. the PC slept), reconnect and carry on."""
        stop = self.stop_event
        if self.settings.keep_awake:
            power.keep_awake(True)
        lost = False
        try:
            if nexlinq.running():            # it fights over the panel; skipped if it isn't installed/open
                self.log(nexlinq.quit_nexlinq())
            from matrix.transport import Matrix
            while not stop.is_set():
                panel = None
                try:
                    panel = Matrix()
                    self.log("Display reconnected." if lost else "Ticker started.")
                    lost = False
                    self.ticker = ScrollTicker(panel, self.settings, log=self.log, stop_event=stop,
                                               counter=self.counter, timer=self.timer)
                    self.ticker.run()
                    self.log("Ticker stopped." if stop.is_set() else "Ticker finished.")
                    if not self._restarting:          # about to start again: skip the flash of the old layout
                        self.log(restore_layout(panel))
                    break
                except Exception as e:
                    if stop.is_set():
                        break
                    if not lost:
                        self.log(f"Lost the display ({e}). Retrying every {self.RECONNECT_S} s…")
                    lost = True
                finally:
                    self.ticker = None
                    if panel:
                        try:
                            panel.close()
                        except Exception:
                            pass
                end = time.time() + self.RECONNECT_S
                while time.time() < end and not stop.is_set():
                    time.sleep(0.2)
        finally:
            power.keep_awake(False)

    def _stop_and_wait(self):
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            self.thread.join(timeout=5)

    def launch_nexlinq(self):
        self._stop_and_wait()
        msg = nexlinq.launch_nexlinq()
        if msg is None:
            path = filedialog.askopenfilename(title="Where is NexLinq? (pick its .exe)",
                                              filetypes=[("Programs", "*.exe")])
            msg = nexlinq.launch_nexlinq(path) if path else "Launch cancelled."
        self.log(msg)

    # ---------- system tray ----------
    def _start_tray(self):
        if pystray is None:
            return
        def later(fn):          # tray callbacks run on the tray thread; hand them to Tk
            return lambda *_: self.cmdq.put(fn)
        running = lambda *_: self.thread is not None and self.thread.is_alive()
        menu = pystray.Menu(
            pystray.MenuItem("Open Matrix Ticker", later(self.show), default=True),
            pystray.MenuItem(lambda item: "Stop ticker" if running() else "Run ticker", later(self.toggle_run)),
            pystray.MenuItem("Launch NexLinq", later(self.launch_nexlinq)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", later(self.quit)),
        )
        try:
            self.tray = pystray.Icon("MatrixTicker", make_image(64), "Matrix Ticker: stopped", menu)
            self.tray.run_detached()
        except Exception as e:
            self.tray = None
            self.log(f"System tray unavailable ({e}); closing the window will quit.")

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _minimized(self, event):
        """The minimize button sends the window to the tray instead of the taskbar."""
        if event.widget is self.root and self.tray and self.root.state() == "iconic":
            self.root.after(10, self.root.withdraw)

    def hide_or_quit(self):
        if not self.tray:
            self.quit()
            return
        self.root.withdraw()
        if not self._told_tray:
            self._told_tray = True
            try:
                self.tray.notify("Still running in the system tray. Right-click the icon to quit.", "Matrix Ticker")
            except Exception:
                pass

    def quit(self):
        self.counter.stop_listening()
        self.timer.stop_listening()
        self._stop_and_wait()
        if self._save_job:
            self._save()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self._closed = True
        self.root.destroy()


def already_running():
    """Windows: a named mutex keeps a second copy (e.g. startup + manual launch) from
    fighting over the panel. Returns True if another copy holds it."""
    if sys.platform != "win32":
        return False
    global _mutex
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "MatrixTicker.SingleInstance")
    return ctypes.windll.kernel32.GetLastError() == 183   # ERROR_ALREADY_EXISTS


if __name__ == "__main__":
    if already_running():
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showinfo("Matrix Ticker", "Matrix Ticker is already running.\n"
                            "Look for its icon in the system tray (near the clock).")
        sys.exit(0)
    if sys.platform == "win32":
        try:  # use our icon on the taskbar instead of Python's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("zaycation.matrixticker")
        except Exception:
            pass
    root = ctk.CTk()
    hidden = "--tray" in sys.argv and pystray is not None
    app = App(root)
    if hidden and app.tray:
        root.withdraw()          # started by Windows at login: stay in the tray
        root.after(400, root.withdraw)   # customtkinter re-shows the window once while styling the title bar
    root.mainloop()
