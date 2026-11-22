"""Print the numbers behind the dashboard meters, once a second, to check them.

    python tools/stats.py

Compare with Task Manager -> Performance: "CPU" and "GPU 0" utilization.
Each meter is 15 LEDs wide; the bars show how many of them light up.
  CPU meter = CPU load (0-100 %)
  GPU meter = GPU load (0-100 %); temperature is printed for reference only
Ctrl+C to stop.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from matrix import system  # noqa: E402

W = 15


def lit(frac):
    return round(max(0.0, min(1.0, frac)) * W)


def bar(n):
    return "#" * n + "." * (W - n)


def main():
    if system.psutil is None:
        print("psutil isn't installed, so CPU load is unavailable: pip install psutil")
    if system._gpu() is None:
        print("NVIDIA stats unavailable (no NVIDIA card, driver, or nvidia-ml-py): pip install nvidia-ml-py")
    print(f"{'CPU load':>9} {'CPU meter':>17}   {'GPU temp':>8} {'GPU load':>8} {'GPU meter':>17}")
    try:
        while True:
            time.sleep(1)
            cpu = system.cpu_load()
            gt, gl = system.gpu_temp(), system.gpu_load()
            cpu_n = lit((cpu or 0) / 100)
            gpu_n = lit((gl or 0) / 100)
            print(f"{'-' if cpu is None else f'{cpu:.0f}%':>9}  [{bar(cpu_n)}]   "
                  f"{'-' if gt is None else f'{gt} C':>8} {'-' if gl is None else f'{gl}%':>8}  [{bar(gpu_n)}]",
                  flush=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
