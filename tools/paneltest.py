"""Check what the panel can display. Run from the folder containing main.py.

    python tools/paneltest.py chars     # which punctuation renders
    python tools/paneltest.py colors    # which colors look right

Each test line is sent, then waits for Enter before the next one.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from matrix.transport import Matrix  # noqa: E402

# Each symbol follows a label letter, so a missing symbol (drawn as "A") is easy to spot.
CHAR_LINES = [
    "B: C- D@ E/ F. G, H# I+",
    "J& K( L) M! N? O' P% Q*",
    "R= S< T> U_ V; W$ X\" Y~",
]
COLORS = [
    ("RED", (255, 0, 0)), ("GREEN", (0, 255, 0)), ("BLUE", (0, 0, 255)),
    ("WHITE", (255, 255, 255)), ("LIVE GREEN", (0, 255, 80)),
    ("FINAL GRAY", (170, 170, 170)), ("DIM GRAY", (80, 80, 80)),
    ("YELLOW", (255, 200, 0)), ("ORANGE", (255, 100, 0)),
]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "chars"
    panel = Matrix()
    try:
        if mode == "chars":
            for line in CHAR_LINES:
                panel.show_text(line)
                input(f"Showing: {line}\n  Note any symbol that shows as 'A' or blank, then press Enter...")
        elif mode == "colors":
            for name, rgb in COLORS:
                panel.show_text(name, color=rgb)
                input(f"Showing {name} {rgb}: does it look right? Press Enter...")
        else:
            print(__doc__)
    finally:
        panel.close()


if __name__ == "__main__":
    main()
