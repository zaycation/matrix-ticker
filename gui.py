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
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from matrix import nexlinq
from matrix.counter import Counter
from matrix.ticker import COUNTER, ITEMS, ScrollTicker, Settings, restore_layout

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

    def __init__(self, root):
        self.root = root
        self.settings = Settings(verbose=True)
        self.thread, self.stop_event = None, threading.Event()
        self.logq, self._save_job = queue.Queue(), None

        saved = load_cfg().get("gui", {})
        for key in ("speed", "padding", "brightness", "loop", "location", "units", "weather_mode",
                    "weather_count", "screen_seconds", "clock_24h"):
            if key in saved:
                setattr(self.settings, key, saved[key])
        if "leagues" in saved:
            self.settings.leagues = [lg for lg in ITEMS if lg in saved["leagues"]]
        self.cmdq, self.tray, self._told_tray, self._closed = queue.Queue(), None, False, False
        self.ticker = None
        self.counter = Counter(on_change=self._counter_bumped)

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
        box = self._card(outer, "Ticker")
        self.vars = {}
        for r, (attr, label, lo, hi, step, cast) in enumerate(self.SLIDERS, start=1):
            self._slider(box, r, attr, label, lo, hi, step, cast)

        # what to show
        box2 = self._card(outer, "Show")
        grid = ctk.CTkFrame(box2, fg_color="transparent")
        grid.grid(row=1, column=0, columnspan=3, sticky="w")
        self.league_vars = {}
        for i, lg in enumerate(ITEMS):
            v = tk.BooleanVar(value=lg in self.settings.leagues)
            self._check(grid, lg, v, self._leagues_changed).grid(row=i // 4, column=i % 4, sticky="w",
                                                                 padx=(0, 12), pady=3)
            self.league_vars[lg] = v

        # weather
        box_w = self._card(outer, "Weather")
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

        # options
        box_o = self._card(outer, "Options")
        self.loop = tk.BooleanVar(value=self.settings.loop)
        self.autorun = tk.BooleanVar(value=saved.get("autorun", False))
        self.h24 = tk.BooleanVar(value=self.settings.clock_24h)
        sw = ctk.CTkFrame(box_o, fg_color="transparent")
        sw.grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 2))
        for text, var, cmd in (("Loop", self.loop, self._opts_changed),
                               ("24-hour clock", self.h24, self._opts_changed),
                               ("Run when the app opens", self.autorun, self._schedule_save)):
            self._switch(sw, text, var, cmd).pack(side="left", padx=(0, 14))
        self.opacity = tk.IntVar(value=int(saved.get("opacity", DEFAULT_OPACITY)))
        self._row_slider(box_o, 2, "Window opacity", self.opacity, 60, 100, 5, "%", self._opacity_changed)

        # counter (only shown when COUNTER is ticked)
        self.counter_box = box3 = self._card(outer, "Counter", pack=False)
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
        self.small = small = ctk.CTkFrame(outer, fg_color="transparent")
        small.pack(fill="x", pady=(10, 0))
        for i, (text, cmd) in enumerate((("Quit", self.quit), ("Reset", self.reset_defaults),
                                         ("Launch NexLinq", self.launch_nexlinq))):
            self._button(small, text, cmd, height=34).grid(row=0, column=i, sticky="ew",
                                                          padx=(0 if i == 0 else 4, 0))
            small.columnconfigure(i, weight=1, uniform="b")

        # log
        self.logbox = ctk.CTkTextbox(outer, height=74, fg_color=CARD, text_color=MUTED, corner_radius=12,
                                     font=ctk.CTkFont(family="Consolas", size=12), wrap="word",
                                     state="disabled", activate_scrollbars=True)
        self.logbox.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(outer, text="Scores: ESPN  ·  Weather data by Open-Meteo.com", text_color=MUTED,
                     font=font(10)).pack(anchor="e", pady=(4, 0))

        self._show_counter_box()
        self._opacity_changed()
        err = self.counter.listen()
        if err:
            self.log(err)
        root.protocol("WM_DELETE_WINDOW", self.hide_or_quit)
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
        card = self.counter_box.card
        if self.league_vars[COUNTER].get():
            if not card.winfo_manager():
                card.pack(fill="x", pady=(8, 0), before=self.small)
        else:
            card.pack_forget()

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

    def _counter_label(self):
        self.counter.label = self.c_label.get().strip() or "COUNT"
        self.counter.save()

    def _set_hotkey(self):
        err = self.counter.listen(self.c_hotkey.get().strip())
        self.log(err or f"Counter shortcut: {self.counter.hotkey}")

    # ---------- settings ----------
    def _leagues_changed(self):
        self.settings.leagues = [lg for lg, v in self.league_vars.items() if v.get()]
        self._show_counter_box()
        self._schedule_save()

    def _location_changed(self):
        self.settings.location = self.location.get().strip()
        self.settings.units = self.units.get().lstrip("°")
        self.settings.weather_mode = self.WMODES[self.wmode.get()]
        self.settings.weather_count = int(self.wcount.get() or 5)
        self._schedule_save()

    def _opts_changed(self):
        self.settings.loop = self.loop.get()
        self.settings.clock_24h = self.h24.get()
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
                      "clock_24h": s.clock_24h, "opacity": self.opacity.get()}
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

    def _worker(self):
        panel = None
        try:
            if nexlinq.running():            # it fights over the panel; skipped if it isn't installed/open
                self.log(nexlinq.quit_nexlinq())
            from matrix.transport import Matrix
            panel = Matrix()
            self.log("Ticker started.")
            self.ticker = ScrollTicker(panel, self.settings, log=self.log, stop_event=self.stop_event,
                                       counter=self.counter)
            self.ticker.run()
            self.log("Ticker stopped." if self.stop_event.is_set() else "Ticker finished.")
        except Exception as e:
            self.log(f"Error: {e}")
        finally:
            self.ticker = None
            if panel:
                try:
                    if not self._restarting:          # about to start again: skip the flash of the old layout
                        self.log(restore_layout(panel))
                finally:
                    panel.close()

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
