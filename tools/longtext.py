"""Does the text command accept more than one packet (100 characters)?

    python tools/longtext.py

Tries two guesses at a "packet number" field in the text packet. Each sends
FIRST... as packet 0 and SECOND... as packet 1. Watch whether the panel
scrolls both halves (works), only one half, or nothing. Restores your layout after.
Uses only the text path (the image path is the one that froze the panel).
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from matrix.transport import Matrix, update_packets  # noqa: E402

PART0 = ("FIRST HALF " * 5)[:50]
PART1 = ("SECOND HALF " * 5)[:50]


def text_chunk(text, b2, b4):
    data = text.encode()
    pkt = bytes([0x01, 0x02, b2, 0x00, b4, len(data) + 1, 0x00]) + data
    return pkt + b"\xff" * (50 - len(data)) + b"\x00" * 7


VARIANTS = [
    ("A: packet number in byte 4", [(0x00, 0), (0x00, 1)]),
    ("B: total count in byte 2 + packet number in byte 4", [(0x02, 0), (0x02, 1)]),
]


def main():
    panel = Matrix()
    try:
        for name, fields in VARIANTS:
            begin, prep, _, widget = update_packets("X")   # reuse the known-good wrapper
            pkts = [begin, prep] + [text_chunk(t, b2, b4) for t, (b2, b4) in zip((PART0, PART1), fields)] + [widget]
            for p, gap in zip(pkts, [0.1, 0.1, 0.05, 0.05, 0]):
                panel.dev.write(p)
                panel._wait_echo(p)
                time.sleep(gap)
            input(f"\n{name}\n  What scrolls: FIRST and SECOND, only FIRST, only SECOND, or nothing? Enter...")
    finally:
        path = os.path.join(ROOT, "layouts", "default.json")
        if os.path.exists(path):
            with open(path) as f:
                panel.replay([bytes.fromhex(h) for h in json.load(f)["packets"]])
            print("Restored your NexLinq layout.")
        panel.close()


if __name__ == "__main__":
    main()
