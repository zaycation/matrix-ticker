"""Pixel tests for the EDITOR (bitmap) path. Run from the folder containing main.py.

    python tools/drawtest.py order   # how the 900 pixels map onto the screen
    python tools/drawtest.py anim            # speed: full upload every frame, no extra waits
    python tools/drawtest.py anim data03     # first frame full, then data + 03 only
    python tools/drawtest.py anim data       # first frame full, then data only
    python tools/drawtest.py gap             # how long the panel needs between frames
    python tools/drawtest.py gap data03      # same, skipping begin/prepare after frame 1
    python tools/drawtest.py wide            # does the panel scroll an image wider than 90 px?

NexLinq must be fully closed for these.

Restores layouts/default.json at the end if it exists.
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from matrix.transport import Matrix  # noqa: E402

N = 900
RED, BLUE, WHITE = b"\xff\x00\x00", b"\x00\x00\xff", b"\xff\xff\xff"


def frame(lit):
    """lit: {pixel_index: rgb_bytes}"""
    buf = bytearray(N * 3)
    for i, c in lit.items():
        buf[i * 3:i * 3 + 3] = c
    return bytes(buf)


def restore(panel):
    from matrix.paths import RESTORE_FILE as path
    if os.path.exists(path):
        with open(path) as f:
            panel.replay([bytes.fromhex(h) for h in json.load(f)["packets"]])
        print("Restored your NexLinq layout.")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "order"
    log = []
    panel = Matrix(log=log)
    try:
        if mode == "order":
            lit = {i: RED for i in range(0, 10)}           # pixels 0-9
            lit.update({i: BLUE for i in range(90, 100)})  # pixels 90-99
            ok, msg = panel.show_bitmap(frame(lit))
            print("upload:", msg)
            input("Sent: pixels 0-9 RED, pixels 90-99 BLUE.\n"
                  "Look at the panel and note, for RED and for BLUE:\n"
                  "  - a horizontal line or a vertical line?\n"
                  "  - where: left or right end, top or bottom?\n"
                  "Then press Enter...")
        elif mode == "anim":
            steps = sys.argv[2] if len(sys.argv) > 2 else "full"
            frames = 60
            t0 = time.perf_counter()
            for i in range(frames):
                ok, msg = panel.show_bitmap(frame({i: WHITE}), steps="full" if i == 0 else steps)
                if not ok:
                    print(f"frame {i}: {msg}")
                    break
            else:
                dt = time.perf_counter() - t0
                print(f"[{steps}] {frames} frames in {dt:.2f} s = {frames / dt:.1f} frames/s")
            input("Did the dot move along the top row the whole time? Smoothly, or with\n"
                  "blanks/flicker, or did it stop moving? Then Enter...")
        elif mode == "wide":
            for width in (180, 255):
                buf = bytearray(width * 10 * 3)
                for y in range(10):
                    for x in range(width):
                        c = WHITE if x in (0, width - 1) else (RED if x < width // 2 else BLUE)
                        i = (y * width + x) * 3
                        buf[i:i + 3] = c
                ok, msg = panel.show_bitmap(bytes(buf), width=width)
                print(f"[{width} px wide] upload: {msg}")
                if not ok:
                    break
                input(f"Image is {width} px: white edge, red half, blue half, white edge.\n"
                      "  Does it scroll across the panel? Do you see BOTH the red and the blue part\n"
                      "  go by (and the white edges)? Or only part of it, or nothing? Then Enter...")
        elif mode == "gap":
            # The dot keeps moving right; each stage waits longer after every frame.
            steps = sys.argv[2] if len(sys.argv) > 2 else "full"
            pos, results = 0, []
            panel.show_bitmap(frame({}))
            time.sleep(0.3)
            for gap in (0.0, 0.05, 0.1, 0.15, 0.3):
                t0 = time.perf_counter()
                for _ in range(8):
                    ok, msg = panel.show_bitmap(frame({pos: WHITE}), steps=steps)
                    if not ok:
                        print(f"pixel {pos}: {msg}")
                        return
                    pos += 1
                    time.sleep(gap)
                fps = 8 / (time.perf_counter() - t0)
                ans = input(f"Wait {gap:.2f}s after each frame ({fps:.1f} frames/s): did the dot move "
                            f"on every frame? (y / some / n) ").strip().lower()
                results.append((gap, fps, ans))
            print(f"\nSummary ({steps}):")
            for gap, fps, ans in results:
                print(f"  wait {gap:.2f}s  {fps:4.1f} frames/s  moved: {ans}")
        else:
            print(__doc__)
    finally:
        upload_end = len(log)
        restore(panel)
        panel.close()
        path = os.path.join(ROOT, "upload_log.txt")
        with open(path, "w") as f:
            f.write("\n".join(log[:upload_end]) + "\n")
        print(f"Log of every packet written (W) and read (R): {path}")


if __name__ == "__main__":
    main()
