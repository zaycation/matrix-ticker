"""Draw static 90x10 screens (dashboard, calendar, counter) pixel by pixel.

Three text sizes:
- small: 3x5 font (two lines fit on the panel)
- normal: the panel font (5x8, matching Phanteks' own)
- big: the panel font at a chosen height (clock, counter, timer)
"""
from . import font

W, H = 90, 10

SMALL = {
    "A": [".#.", "#.#", "###", "#.#", "#.#"], "B": ["##.", "#.#", "##.", "#.#", "##."],
    "C": [".##", "#..", "#..", "#..", ".##"], "D": ["##.", "#.#", "#.#", "#.#", "##."],
    "E": ["###", "#..", "##.", "#..", "###"], "F": ["###", "#..", "##.", "#..", "#.."],
    "G": [".##", "#..", "#.#", "#.#", ".##"], "H": ["#.#", "#.#", "###", "#.#", "#.#"],
    "I": ["###", ".#.", ".#.", ".#.", "###"], "J": ["..#", "..#", "..#", "#.#", ".#."],
    "K": ["#.#", "#.#", "##.", "#.#", "#.#"], "L": ["#..", "#..", "#..", "#..", "###"],
    "M": ["#.#", "###", "###", "#.#", "#.#"], "N": ["##.", "#.#", "#.#", "#.#", "#.#"],
    "O": [".#.", "#.#", "#.#", "#.#", ".#."], "P": ["##.", "#.#", "##.", "#..", "#.."],
    "Q": [".#.", "#.#", "#.#", "##.", ".##"], "R": ["##.", "#.#", "##.", "#.#", "#.#"],
    "S": [".##", "#..", ".#.", "..#", "##."], "T": ["###", ".#.", ".#.", ".#.", ".#."],
    "U": ["#.#", "#.#", "#.#", "#.#", "###"], "V": ["#.#", "#.#", "#.#", "#.#", ".#."],
    "W": ["#.#", "#.#", "###", "###", "#.#"], "X": ["#.#", "#.#", ".#.", "#.#", "#.#"],
    "Y": ["#.#", "#.#", ".#.", ".#.", ".#."], "Z": ["###", "..#", ".#.", "#..", "###"],
    "0": ["###", "#.#", "#.#", "#.#", "###"], "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["##.", "..#", ".#.", "#..", "###"], "3": ["##.", "..#", ".#.", "..#", "##."],
    "4": ["#.#", "#.#", "###", "..#", "..#"], "5": ["###", "#..", "##.", "..#", "##."],
    "6": [".##", "#..", "###", "#.#", "###"], "7": ["###", "..#", ".#.", ".#.", ".#."],
    "8": ["###", "#.#", "###", "#.#", "###"], "9": ["###", "#.#", "###", "..#", "##."],
    ":": [".", "#", ".", "#", "."], ".": [".", ".", ".", ".", "#"], "-": ["...", "...", "###", "...", "..."],
    "%": ["#.#", "..#", ".#.", "#..", "#.#"], "/": ["..#", "..#", ".#.", "#..", "#.."],
    "°": [".#.", "#.#", ".#.", "...", "..."], " ": ["..", "..", "..", "..", ".."],
    "+": ["...", ".#.", "###", ".#.", "..."], "'": ["#", "#", ".", ".", "."],
}
# 3x4 letters for labels that need a gap between two lines (dashboard CPU / GPU)
TINY = {
    "C": [".##", "#..", "#..", ".##"], "P": ["##.", "#.#", "##.", "#.."],
    "U": ["#.#", "#.#", "#.#", "###"], "G": [".##", "#..", "#.#", ".##"],
    "R": ["##.", "#.#", "##.", "#.#"], "A": [".#.", "#.#", "###", "#.#"],
    "M": ["#.#", "###", "#.#", "#.#"], " ": ["..", "..", "..", ".."],
}


class Canvas:
    def __init__(self):
        self.px = [[(0, 0, 0)] * W for _ in range(H)]

    def set(self, x, y, rgb):
        if 0 <= x < W and 0 <= y < H and rgb:
            self.px[y][x] = rgb

    def rect(self, x0, y0, x1, y1, rgb):
        """Filled rectangle, inclusive corners."""
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.set(x, y, rgb)

    # ---- text ----
    def small(self, text, x, y, rgb):
        """3x5 text at (x, y) = top-left. Returns the x after the text."""
        for ch in text.upper():
            rows = SMALL.get(ch, SMALL[" "])
            for dy, row in enumerate(rows):
                for dx, c in enumerate(row):
                    if c == "#":
                        self.set(x + dx, y + dy, rgb)
            x += len(rows[0]) + 1
        return x - 1

    def tiny(self, text, x, y, rgb):
        """3x4 text at (x, y) = top-left. Returns the x after the text."""
        for ch in text.upper():
            rows = TINY.get(ch, TINY[" "])
            for dy, row in enumerate(rows):
                for dx, c in enumerate(row):
                    if c == "#":
                        self.set(x + dx, y + dy, rgb)
            x += len(rows[0]) + 1
        return x - 1

    def normal(self, text, x, y, rgb):
        """Panel font (5x8, see font.py) at (x, y) = top-left. Returns the x after the text."""
        for ch in text:
            icon = ch in font.ICONS
            cols = font.icon_columns(ch) if icon else font.glyph_columns(ch)
            dy0 = 1 if icon else 0          # 7-row icons sit one row down, level with the letters' bottoms
            for dx, col in enumerate(cols):
                for dy, on in enumerate(col):
                    if on:
                        self.set(x + dx, y + dy0 + dy, on if isinstance(on, tuple) else rgb)
            x += len(cols) + font.GAP
        return x - font.GAP

    def big(self, text, x, rgb, top=1, height=8):
        """Tall text: the panel font's 8 letter rows, stretched or squeezed to `height` rows
        starting at `top` (at the default height of 8 it's the font as-is). Returns end x."""
        rows = [int(y * 8 / height) for y in range(height)]
        for ch in text:
            cols = font.glyph_columns(ch)
            for dx, col in enumerate(cols):
                for y in range(height):
                    if col[rows[y]]:
                        self.set(x + dx, top + y, rgb)
            x += len(cols) + font.GAP
        return x - font.GAP

    def to_bytes(self):
        return bytes(c for row in self.px for px in row for c in px)


def small_width(text):
    return sum(len(SMALL.get(ch, SMALL[" "])[0]) + 1 for ch in text.upper()) - 1 if text else 0


def normal_width(text):
    return font.text_width(text)


def big_width(text):
    return font.text_width(text)       # same columns as the normal font
