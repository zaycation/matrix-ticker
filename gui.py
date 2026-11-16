"""Matrix Ticker control window (tkinter: built into Python, nearly zero CPU when idle).

    pythonw gui.py        # no console window
    python gui.py         # with a console (shows errors)

Settings are saved to config.json under "gui".
"""
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from matrix import nexlinq, scores
from matrix.ticker import ScrollTicker, Settings, restore_layout

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(ROOT, "config.json")


def load_cfg():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class App:
    def __init__(self, root):
        self.root = root
        self.settings = Settings()
        self.thread, self.stop_event = None, threading.Event()
        self.logq = queue.Queue()

        saved = load_cfg().get("gui", {})
        for key in ("speed", "padding", "brightness", "loop", "verbose"):
            if key in saved:
                setattr(self.settings, key, saved[key])
        if "leagues" in saved:
            self.settings.leagues = [lg for lg in scores.ALL if lg in saved["leagues"]]
        self.close_nexlinq = tk.BooleanVar(value=saved.get("close_nexlinq", True))

        root.title("Matrix Ticker")
        root.resizable(False, False)
        pad = {"padx": 8, "pady": 3}
        frm = ttk.Frame(root, padding=10)
        frm.grid()

        self.status = tk.StringVar(value="Stopped")
        ttk.Label(frm, textvariable=self.status, font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", **pad)

        # sliders (apply live)
        self.speed = self._slider(frm, 1, "Speed (px/s)", 6, 24, self.settings.speed, 0.5, "speed", float)
        self.padding = self._slider(frm, 2, "Padding (spaces)", 1, 15, self.settings.padding, 1, "padding", int)
        self.bright = self._slider(frm, 3, "Brightness (%)", 10, 100, self.settings.brightness, 5, "brightness", int)

        # sports
        ttk.Label(frm, text="Sports").grid(row=4, column=0, sticky="w", **pad)
        box = ttk.Frame(frm)
        box.grid(row=4, column=1, columnspan=3, sticky="w")
        self.league_vars = {}
        for i, lg in enumerate(scores.ALL):
            v = tk.BooleanVar(value=lg in self.settings.leagues)
            ttk.Checkbutton(box, text=lg, variable=v, command=self._leagues_changed).grid(
                row=i // 4, column=i % 4, sticky="w", padx=3)
            self.league_vars[lg] = v

        # options
        opts = ttk.Frame(frm)
        opts.grid(row=5, column=0, columnspan=4, sticky="w", **pad)
        self.loop = tk.BooleanVar(value=self.settings.loop)
        self.verbose = tk.BooleanVar(value=self.settings.verbose)
        ttk.Checkbutton(opts, text="Loop", variable=self.loop, command=self._opts_changed).grid(row=0, column=0, padx=4)
        ttk.Checkbutton(opts, text="Verbose log", variable=self.verbose, command=self._opts_changed).grid(row=0, column=1, padx=4)
        ttk.Checkbutton(opts, text="Close NexLinq on Run", variable=self.close_nexlinq,
                        command=self._save).grid(row=0, column=2, padx=4)

        # buttons
        b = ttk.Frame(frm)
        b.grid(row=6, column=0, columnspan=4, pady=(6, 2))
        rows = [[("Run", self.run), ("Stop", self.stop)],
                [("Quit NexLinq", self.quit_nexlinq), ("Launch NexLinq", self.launch_nexlinq)],
                [("Quit", self.quit), ("Quit + launch NexLinq", self.quit_and_launch)]]
        for r, row in enumerate(rows):
            for c, (text, cmd) in enumerate(row):
                ttk.Button(b, text=text, command=cmd, width=22).grid(row=r, column=c, padx=4, pady=2)

        # log
        self.logbox = tk.Text(frm, height=8, width=60, state="disabled", font=("Consolas", 9))
        self.logbox.grid(row=7, column=0, columnspan=4, pady=(6, 0))

        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(200, self._drain_log)

    # ---------- controls ----------
    def _slider(self, frm, row, label, lo, hi, value, step, attr, cast):
        ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=3)
        var = tk.DoubleVar(value=value)
        shown = tk.StringVar(value=str(cast(value)))

        def changed(_=None):
            v = cast(round(var.get() / step) * step)
            shown.set(str(v))
            setattr(self.settings, attr, v)
            self._save()
        ttk.Scale(frm, from_=lo, to=hi, variable=var, length=260, command=changed).grid(
            row=row, column=1, columnspan=2, sticky="w")
        ttk.Label(frm, textvariable=shown, width=5).grid(row=row, column=3, sticky="w")
        return var

    def _leagues_changed(self):
        self.settings.leagues = [lg for lg, v in self.league_vars.items() if v.get()]
        self._save()

    def _opts_changed(self):
        self.settings.loop, self.settings.verbose = self.loop.get(), self.verbose.get()
        self._save()

    def _save(self):
        cfg = load_cfg()
        s = self.settings
        cfg["gui"] = {"speed": s.speed, "padding": s.padding, "brightness": s.brightness,
                      "leagues": s.leagues, "loop": s.loop, "verbose": s.verbose,
                      "close_nexlinq": self.close_nexlinq.get()}
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)

    def log(self, msg):
        self.logq.put(msg)

    def _drain_log(self):
        while not self.logq.empty():
            msg = self.logq.get()
            self.logbox.configure(state="normal")
            self.logbox.insert("end", msg + "\n")
            if int(self.logbox.index("end-1c").split(".")[0]) > 300:
                self.logbox.delete("1.0", "50.0")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        running = self.thread is not None and self.thread.is_alive()
        self.status.set("Running" if running else "Stopped")
        self.root.after(200, self._drain_log)

    # ---------- actions ----------
    def run(self):
        if self.thread and self.thread.is_alive():
            self.log("Already running.")
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
            self.log("Ticker finished." if not self.stop_event.is_set() else "Ticker stopped.")
        except Exception as e:
            self.log(f"Error: {e}")
        finally:
            if panel:
                try:
                    self.log(restore_layout(panel))
                finally:
                    panel.close()

    def stop(self, wait=True):
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            if wait:
                self.thread.join(timeout=5)

    def quit_nexlinq(self):
        threading.Thread(target=lambda: self.log(nexlinq.quit_nexlinq()), daemon=True).start()

    def launch_nexlinq(self):
        self.stop()
        msg = nexlinq.launch_nexlinq()
        if msg is None:
            path = filedialog.askopenfilename(title="Where is NexLinq? (pick its .exe)",
                                              filetypes=[("Programs", "*.exe")])
            msg = nexlinq.launch_nexlinq(path) if path else "Launch cancelled."
        self.log(msg)

    def quit(self):
        self.stop()
        self.root.destroy()

    def quit_and_launch(self):
        self.stop()
        self.launch_nexlinq()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
