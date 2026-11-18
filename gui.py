"""Matrix Ticker control window. Dark, lightweight (tkinter, built into Python).

    pythonw gui.py           # no console window
    pythonw gui.py --tray    # start hidden in the system tray (used at Windows startup)

Closing the window keeps it running in the system tray (needs pystray + Pillow).
Settings are saved to config.json under "gui".
"""
import ctypes
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog

from matrix import nexlinq, scores
from matrix.counter import Counter
from matrix.ticker import ITEMS, WEATHER, ScrollTicker, Settings, restore_layout

try:
    import pystray
    from matrix.icon import make_image
except Exception:          # tray is optional when running from source
    pystray = None

from matrix.paths import CONFIG_FILE

BG, PANEL, FG, MUTED = "#15171c", "#1e2128", "#e6e8eb", "#8b919c"
TROUGH, SLIDER, ACCENT = "#2a2e37", "#6b8cff", "#3b4252"
GREEN, GREEN_HI, RED, RED_HI = "#1f9d55", "#25b864", "#c0392b", "#d9443a"
FONT, FONT_B = ("Segoe UI", 10), ("Segoe UI", 10, "bold")


def load_cfg():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def dark_title_bar(root):
    """Windows 10/11: ask for a dark title bar. Harmless elsewhere."""
    if sys.platform != "win32":
        return
    try:
        root.update()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        on = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (newer, older builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4) == 0:
                break
    except Exception:
        pass


def led_icon(size=32):
    """Small dark tile with a few colored 'LEDs', drawn in code (no image files)."""
    img = tk.PhotoImage(width=size, height=size)
    img.put(PANEL, to=(0, 0, size, size))
    colors = ["#ff3b3b", "#ffffff", "#25b864", "#6b8cff", "#ffc72c"]
    cell = size // 6
    for row in range(2, 4):
        for col in range(1, 5):
            c = colors[(row * 4 + col) % len(colors)]
            x, y = col * cell + 1, row * cell + 1
            img.put(c, to=(x, y, x + cell - 2, y + cell - 2))
    return img


class FlatButton(tk.Label):
    """Flat clickable label with hover color (lighter than tk.Button, styles fully)."""
    def __init__(self, parent, text, command, bg=ACCENT, hover=None, font=FONT, **kw):
        super().__init__(parent, text=text, bg=bg, fg=FG, font=font, cursor="hand2", **kw)
        self.command, self.base, self.hover = command, bg, hover or self._lighter(bg)
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Enter>", lambda e: self.configure(bg=self.hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self.base))

    @staticmethod
    def _lighter(hexcolor):
        r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
        return "#%02x%02x%02x" % tuple(min(255, v + 25) for v in (r, g, b))

    def set_style(self, text, bg, hover):
        self.base, self.hover = bg, hover
        self.configure(text=text, bg=bg)


class App:
    SLIDERS = [  # attr, label, low, high, step, cast
        ("speed", "Speed  (pixels/s)", 6, 24, 0.5, float),
        ("padding", "Padding  (spaces)", 1, 15, 1, int),
        ("brightness", "Brightness  (%)", 10, 100, 5, int),
        ("screen_seconds", "Screen time  (s)", 3, 30, 1, int),
    ]

    def __init__(self, root):
        self.root = root
        self.settings = Settings(verbose=True)
        self.thread, self.stop_event = None, threading.Event()
        self.logq, self._save_job = queue.Queue(), None

        saved = load_cfg().get("gui", {})
        for key in ("speed", "padding", "brightness", "loop", "location", "units", "weather_mode",
                    "screen_seconds", "clock_24h"):
            if key in saved:
                setattr(self.settings, key, saved[key])
        if "leagues" in saved:
            self.settings.leagues = [lg for lg in ITEMS if lg in saved["leagues"]]
        self.cmdq, self.tray, self._told_tray, self._closed = queue.Queue(), None, False, False
        self.ticker = None
        self.counter = Counter(on_change=self._counter_bumped)

        root.title("Matrix Ticker")
        root.configure(bg=BG)
        root.resizable(False, False)
        self.icon = led_icon()
        root.iconphoto(True, self.icon)

        outer = tk.Frame(root, bg=BG, padx=14, pady=12)
        outer.pack()

        # header
        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="Matrix Ticker", bg=BG, fg=FG, font=("Segoe UI", 13, "bold")).pack(side="left")
        self.status = tk.Label(head, text="● Stopped", bg=BG, fg=MUTED, font=FONT)
        self.status.pack(side="right")

        # big run/stop toggle
        self.toggle = FlatButton(outer, "▶   Run", self.toggle_run, bg=GREEN, hover=GREEN_HI,
                                 font=("Segoe UI", 14, "bold"), pady=10)
        self.toggle.pack(fill="x", pady=(10, 12))

        # sliders
        box = tk.Frame(outer, bg=PANEL, padx=12, pady=8)
        box.pack(fill="x")
        self.vars = {}
        for r, (attr, label, lo, hi, step, cast) in enumerate(self.SLIDERS):
            self._slider(box, r, attr, label, lo, hi, step, cast)

        # sports + options
        box2 = tk.Frame(outer, bg=PANEL, padx=12, pady=8)
        box2.pack(fill="x", pady=(8, 0))
        tk.Label(box2, text="Show", bg=PANEL, fg=MUTED, font=FONT).grid(row=0, column=0, sticky="w")
        self.league_vars = {}
        for i, lg in enumerate(ITEMS):
            v = tk.BooleanVar(value=lg in self.settings.leagues)
            self._check(box2, lg, v, self._leagues_changed).grid(row=1 + i // 4, column=i % 4, sticky="w")
            self.league_vars[lg] = v
        r0 = 1 + -(-len(ITEMS) // 4)                     # first row under the checkboxes
        tk.Label(box2, text="Weather location", bg=PANEL, fg=MUTED, font=FONT).grid(
            row=r0, column=0, columnspan=2, sticky="w", pady=(6, 0))
        loc = tk.Frame(box2, bg=PANEL)
        loc.grid(row=r0 + 1, column=0, columnspan=4, sticky="w")
        self.location = tk.StringVar(value=self.settings.location)
        self.location.trace_add("write", lambda *_: self._location_changed())
        tk.Entry(loc, textvariable=self.location, width=26, bg=TROUGH, fg=FG, insertbackground=FG,
                 relief="flat", font=FONT, highlightthickness=1, highlightbackground=TROUGH,
                 highlightcolor=SLIDER).pack(side="left", ipady=3)
        self.celsius = tk.BooleanVar(value=self.settings.units == "C")
        self._check(loc, "°C", self.celsius, self._location_changed).pack(side="left", padx=(8, 0))
        self.wmode = tk.StringVar(value=self.settings.weather_mode)
        for value, text in (("daily", "5 days"), ("hourly", "5 hours")):
            tk.Radiobutton(loc, text=text, value=value, variable=self.wmode, command=self._location_changed,
                           bg=PANEL, fg=FG, selectcolor=TROUGH, activebackground=PANEL, activeforeground=FG,
                           highlightthickness=0, bd=0, font=FONT).pack(side="left", padx=(8, 0))
        tk.Label(box2, text="City or ZIP, e.g. 91367", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).grid(
            row=r0, column=2, columnspan=2, sticky="e", pady=(6, 0))
        tk.Label(box2, text="Options", bg=PANEL, fg=MUTED, font=FONT).grid(row=r0 + 2, column=0, sticky="w", pady=(6, 0))
        self.loop = tk.BooleanVar(value=self.settings.loop)
        self.close_nexlinq = tk.BooleanVar(value=saved.get("close_nexlinq", True))
        self.autorun = tk.BooleanVar(value=saved.get("autorun", False))
        self._check(box2, "Loop", self.loop, self._opts_changed).grid(row=r0 + 3, column=0, sticky="w")
        self._check(box2, "Close NexLinq on Run", self.close_nexlinq, self._schedule_save).grid(
            row=r0 + 3, column=1, columnspan=3, sticky="w")
        self._check(box2, "Start the ticker when the app opens", self.autorun, self._schedule_save).grid(
            row=r0 + 4, column=0, columnspan=4, sticky="w")
        self.h24 = tk.BooleanVar(value=self.settings.clock_24h)
        self._check(box2, "24-hour clock", self.h24, self._opts_changed).grid(row=r0 + 5, column=0, columnspan=4, sticky="w")

        # counter
        box3 = tk.Frame(outer, bg=PANEL, padx=12, pady=8)
        box3.pack(fill="x", pady=(8, 0))
        tk.Label(box3, text="Counter", bg=PANEL, fg=MUTED, font=FONT).grid(row=0, column=0, sticky="w")
        self.count_label = tk.Label(box3, text=str(self.counter.count), bg=PANEL, fg="#ffc800",
                                    font=("Segoe UI", 16, "bold"), width=5, anchor="e")
        self.count_label.grid(row=0, column=3, rowspan=2, sticky="e")
        tk.Label(box3, text="Label", bg=PANEL, fg=FG, font=FONT).grid(row=1, column=0, sticky="w")
        self.c_label = tk.StringVar(value=self.counter.label)
        self.c_label.trace_add("write", lambda *_: self._counter_label())
        self._entry(box3, self.c_label, 12).grid(row=1, column=1, sticky="w", padx=4)
        tk.Label(box3, text="Shortcut", bg=PANEL, fg=FG, font=FONT).grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.c_hotkey = tk.StringVar(value=self.counter.hotkey)
        self._entry(box3, self.c_hotkey, 12).grid(row=2, column=1, sticky="w", padx=4, pady=(4, 0))
        FlatButton(box3, "Set", self._set_hotkey, padx=8, pady=1, font=("Segoe UI", 9)).grid(
            row=2, column=2, sticky="w", pady=(4, 0))
        cb = tk.Frame(box3, bg=PANEL)
        cb.grid(row=2, column=3, sticky="e", pady=(4, 0))
        for text, cmd in (("−1", lambda: self.counter.add(-1)), ("+1", lambda: self.counter.add(1)),
                          ("Reset", self.counter.reset)):
            FlatButton(cb, text, cmd, padx=6, pady=1, font=("Segoe UI", 9)).pack(side="left", padx=1)
        tk.Label(box3, text="e.g. ctrl+alt+c or f8 (works in games)", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8)).grid(row=3, column=1, columnspan=3, sticky="w", padx=4)
        box3.columnconfigure(2, weight=1)

        # small buttons
        small = tk.Frame(outer, bg=BG)
        small.pack(fill="x", pady=(10, 0))
        buttons = [("Quit NexLinq", self.quit_nexlinq), ("Launch NexLinq", self.launch_nexlinq),
                   ("Reset defaults", self.reset_defaults), ("Quit", self.quit),
                   ("Quit + launch NexLinq", self.quit_and_launch)]
        for i, (text, cmd) in enumerate(buttons):
            FlatButton(small, text, cmd, bg=ACCENT, padx=8, pady=4, font=("Segoe UI", 9)).grid(
                row=i // 3, column=i % 3, sticky="ew", padx=2, pady=2)
        for c in range(3):
            small.columnconfigure(c, weight=1)

        # log
        self.logbox = tk.Text(outer, height=7, width=58, bg=PANEL, fg=MUTED, insertbackground=FG,
                              relief="flat", bd=0, highlightthickness=0, padx=8, pady=6,
                              font=("Consolas", 9), state="disabled")
        self.logbox.pack(fill="x", pady=(10, 0))
        tk.Label(outer, text="Scores: ESPN  ·  Weather data by Open-Meteo.com", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="e", pady=(4, 0))

        err = self.counter.listen()
        if err:
            self.log(err)
        root.protocol("WM_DELETE_WINDOW", self.hide_or_quit)
        dark_title_bar(root)
        self._start_tray()
        root.after(200, self._poll)
        if self.autorun.get():
            root.after(800, self.toggle_run)

    # ---------- widgets ----------
    def _slider(self, parent, row, attr, label, lo, hi, step, cast):
        tk.Label(parent, text=label, bg=PANEL, fg=FG, font=FONT, width=17, anchor="w").grid(row=row, column=0, sticky="w")
        var = tk.DoubleVar(value=getattr(self.settings, attr))
        value = tk.Label(parent, text=str(cast(var.get())), bg=PANEL, fg=FG, font=FONT_B, width=5, anchor="e")

        def changed(_=None):
            v = cast(var.get())
            value.configure(text=str(v))
            setattr(self.settings, attr, v)
            self._schedule_save()

        scale = tk.Scale(parent, from_=lo, to=hi, resolution=step, orient="horizontal", variable=var,
                         showvalue=0, length=230, width=8, sliderlength=16, bd=0, highlightthickness=0,
                         sliderrelief="flat", bg=SLIDER, activebackground="#8fa8ff", troughcolor=TROUGH,
                         command=changed)
        scale.grid(row=row, column=1, padx=6, pady=6)
        value.grid(row=row, column=2, sticky="e")

        def wheel(e):
            var.set(min(hi, max(lo, var.get() + (step if e.delta > 0 else -step))))
            changed()
        scale.bind("<MouseWheel>", wheel)
        self.vars[attr] = (var, changed)

    def _entry(self, parent, var, width):
        return tk.Entry(parent, textvariable=var, width=width, bg=TROUGH, fg=FG, insertbackground=FG,
                        relief="flat", font=FONT, highlightthickness=1, highlightbackground=TROUGH,
                        highlightcolor=SLIDER)

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

    def _check(self, parent, text, var, command):
        return tk.Checkbutton(parent, text=text, variable=var, command=command, bg=PANEL, fg=FG,
                              selectcolor=TROUGH, activebackground=PANEL, activeforeground=FG,
                              highlightthickness=0, bd=0, font=FONT, padx=2, pady=2)

    # ---------- settings ----------
    def _leagues_changed(self):
        self.settings.leagues = [lg for lg, v in self.league_vars.items() if v.get()]
        self._schedule_save()

    def _location_changed(self):
        self.settings.location = self.location.get()
        self.settings.units = "C" if self.celsius.get() else "F"
        self.settings.weather_mode = self.wmode.get()
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
                      "leagues": s.leagues, "loop": s.loop, "close_nexlinq": self.close_nexlinq.get(),
                      "location": s.location, "units": s.units, "weather_mode": s.weather_mode,
                      "autorun": self.autorun.get(), "screen_seconds": s.screen_seconds,
                      "clock_24h": s.clock_24h}
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
        self.close_nexlinq.set(True)
        self.autorun.set(False)
        self.celsius.set(False)
        self.wmode.set("daily")
        self.h24.set(False)
        self._location_changed()
        self._leagues_changed()
        self._opts_changed()
        self.log("Settings reset to defaults.")

    # ---------- log / status ----------
    def log(self, msg):
        self.logq.put(msg)

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
        if running and self.stop_event.is_set():
            self.toggle.set_style("Stopping…", "#7a2a22", "#7a2a22")
            self.status.configure(text="● Stopping", fg="#d9a03a")
        elif running:
            self.toggle.set_style("■   Stop", RED, RED_HI)
            self.status.configure(text="● Running", fg="#25b864")
        else:
            self.toggle.set_style("▶   Run", GREEN, GREEN_HI)
            self.status.configure(text="● Stopped", fg=MUTED)
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
            self.log("Pick at least one sport.")
            return
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        panel = None
        try:
            if self.close_nexlinq.get() and nexlinq.running():
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
                    self.log(restore_layout(panel))
                finally:
                    panel.close()

    def _stop_and_wait(self):
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            self.thread.join(timeout=5)

    def quit_nexlinq(self):
        threading.Thread(target=lambda: self.log(nexlinq.quit_nexlinq()), daemon=True).start()

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

    def quit_and_launch(self):
        self._stop_and_wait()
        self.launch_nexlinq()
        self.quit()


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
    root = tk.Tk()
    hidden = "--tray" in sys.argv and pystray is not None
    if hidden:
        root.withdraw()          # started by Windows at login: stay in the tray
    app = App(root)
    if hidden and not app.tray:
        root.deiconify()         # no tray after all: don't leave an invisible app
    root.mainloop()
