"""Which packets does a text change actually need, and which one causes the refresh?

    python tools/variants.py

Sends a different text with each subset of the update sequence. For each one,
note: did the text change? did the panel visibly blank/flash first?

Full sequence is: 04 begin, 05 prepare, 02 text, 03 widget.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from matrix.transport import Matrix, update_packets  # noqa: E402

VARIANTS = [
    ("FULL 1", ["04", "05", "02", "03"]),   # baseline: known to work
    ("NO PREP 2", ["04", "02", "03"]),      # skip 05
    ("NO BEGIN 3", ["05", "02", "03"]),     # skip 04
    ("TEXT WIDGET 4", ["02", "03"]),        # skip 04 and 05
    ("BEGIN TEXT 5", ["04", "02"]),         # skip 05 and 03
    ("FULL 6", ["04", "05", "02", "03"]),   # baseline again
]


def main():
    panel = Matrix()
    try:
        for text, cmds in VARIANTS:
            pkts = {f"{p[1]:02x}": p for p in update_packets(text)}
            for c in cmds:
                panel.dev.write(pkts[c])
                panel._wait_echo(pkts[c])
                time.sleep(0.1)
            input(f"Sent '{text}' using {' '.join(cmds)}.\n"
                  f"  Did it change to '{text}'? Did it flash/blank first? Then Enter...")
    finally:
        panel.close()


if __name__ == "__main__":
    main()
