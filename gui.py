"""Matrix Ticker control window. Dark, lightweight (tkinter, built into Python).

    pythonw gui.py        # no console window
    python gui.py         # with a console (shows errors)

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
from matrix.ticker import ScrollTicker, Settings, restore_layout

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(ROOT, "config.json")

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
    ]

    def __init__(self, root):
        self.root = root
        self.settings = Settings(verbose=True)
        self.thread, self.stop_event = None, threading.Event()
        self.logq, self._save_job = queue.Queue(), None

        saved = load_cfg().get("gui", {})
        for key in ("speed", "padding", "brightness", "loop"):
            if key in saved:
                setattr(self.settings, key, saved[key])
        if "leagues" in saved:
            self.settings.leagues = [lg for lg in scores.ALL if lg in saved["leagues"]]

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
        tk.Label(box2, text="Sports", bg=PANEL, fg=MUTED, font=FONT).grid(row=0, column=0, sticky="w")
        self.league_vars = {}
        for i, lg in enumerate(scores.ALL):
            v = tk.BooleanVar(value=lg in self.settings.leagues)
            self._check(box2, lg, v, self._leagues_changed).grid(row=1 + i // 4, column=i % 4, sticky="w")
            self.league_vars[lg] = v
        tk.Label(box2, text="Options", bg=PANEL, fg=MUTED, font=FONT).grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.loop = tk.BooleanVar(value=self.settings.loop)
        self.close_nexlinq = tk.BooleanVar(value=saved.get("close_nexlinq", True))
        self._check(box2, "Loop", self.loop, self._opts_changed).grid(row=4, column=0, sticky="w")
        self._check(box2, "Close NexLinq on Run", self.close_nexlinq, self._schedule_save).grid(
            row=4, column=1, columnspan=3, sticky="w")

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

        root.protocol("WM_DELETE_WINDOW", self.quit)
        dark_title_bar(root)
        root.after(200, self._poll)

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

    def _check(self, parent, text, var, command):
        return tk.Checkbutton(parent, text=text, variable=var, command=command, bg=PANEL, fg=FG,
                              selectcolor=TROUGH, activebackground=PANEL, activeforeground=FG,
                              highlightthickness=0, bd=0, font=FONT, padx=2, pady=2)

    # ---------- settings ----------
    def _leagues_changed(self):
        self.settings.leagues = [lg for lg, v in self.league_vars.items() if v.get()]
        self._schedule_save()

    def _opts_changed(self):
        self.settings.loop = self.loop.get()
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
                      "leagues": s.leagues, "loop": s.loop, "close_nexlinq": self.close_nexlinq.get()}
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
        self._leagues_changed()
        self._opts_changed()
        self.log("Settings reset to defaults.")

    # ---------- log / status ----------
    def log(self, msg):
        self.logq.put(msg)

    def _poll(self):
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
            ScrollTicker(panel, self.settings, log=self.log, stop_event=self.stop_event).run()
            self.log("Ticker stopped." if self.stop_event.is_set() else "Ticker finished.")
        except Exception as e:
            self.log(f"Error: {e}")
        finally:
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

    def quit(self):
        self._stop_and_wait()
        if self._save_job:
            self._save()
        self.root.destroy()

    def quit_and_launch(self):
        self._stop_and_wait()
        self.launch_nexlinq()
        self.quit()


if __name__ == "__main__":
    if sys.platform == "win32":
        try:  # use our icon on the taskbar instead of Python's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("zaycation.matrixticker")
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()
