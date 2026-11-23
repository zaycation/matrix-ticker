"""Print the numbers behind the dashboard meters, once a second, to check them.

    python tools/stats.py

Compare with Task Manager -> Performance ("CPU", "Memory", "GPU 0").
These are every value the dashboard meters can show (pick them in the app under Options).
Each meter is 15 LEDs wide; temperature fills it over 30-90 C, the rest over 0-100 %.
Ctrl+C to stop.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from matrix import system  # noqa: E402

def main():
    if system.psutil is None:
        print("psutil isn't installed, so CPU load is unavailable: pip install psutil")
    if system._gpu() is None:
        print("NVIDIA stats unavailable (no NVIDIA card, driver, or nvidia-ml-py): pip install nvidia-ml-py")
    names = [("CPU load", system.cpu_load, "%"), ("Busy core", system.cpu_peak, "%"), ("RAM", system.ram_used, "%"), ("GPU temp", system.gpu_temp, " C"),
             ("GPU load", system.gpu_load, "%"), ("VRAM", system.gpu_vram, "%"),
             ("Power", system.gpu_power, "%"), ("Fan", system.gpu_fan, "%")]
    print("  ".join(f"{n:>9}" for n, _, _ in names))
    try:
        while True:
            time.sleep(1)
            vals = []
            for _, fn, unit in names:
                v = fn()
                vals.append("-" if v is None else f"{v:.0f}{unit}")
            print("  ".join(f"{v:>9}" for v in vals), flush=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
