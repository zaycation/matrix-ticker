"""5x7 pixel font, drawn proportionally (narrow glyphs like 1 : . take less space).

Each glyph is 7 rows of 5-bit masks, most significant bit = leftmost column.
Unknown characters render as a blank space.
"""

GLYPHS = {
    "0": [14, 17, 19, 21, 25, 17, 14], "1": [4, 12, 4, 4, 4, 4, 14],
    "2": [14, 17, 1, 2, 4, 8, 31], "3": [31, 2, 4, 2, 1, 17, 14],
    "4": [2, 6, 10, 18, 31, 2, 2], "5": [31, 16, 30, 1, 1, 17, 14],
    "6": [6, 8, 16, 30, 17, 17, 14], "7": [31, 1, 2, 4, 8, 8, 8],
    "8": [14, 17, 17, 14, 17, 17, 14], "9": [14, 17, 17, 15, 1, 2, 12],
    "A": [14, 17, 17, 31, 17, 17, 17], "B": [30, 17, 17, 30, 17, 17, 30],
    "C": [14, 17, 16, 16, 16, 17, 14], "D": [30, 17, 17, 17, 17, 17, 30],
    "E": [31, 16, 16, 30, 16, 16, 31], "F": [31, 16, 16, 30, 16, 16, 16],
    "G": [14, 17, 16, 23, 17, 17, 15], "H": [17, 17, 17, 31, 17, 17, 17],
    "I": [14, 4, 4, 4, 4, 4, 14], "J": [7, 2, 2, 2, 2, 18, 12],
    "K": [17, 18, 20, 24, 20, 18, 17], "L": [16, 16, 16, 16, 16, 16, 31],
    "M": [17, 27, 21, 21, 17, 17, 17], "N": [17, 17, 25, 21, 19, 17, 17],
    "O": [14, 17, 17, 17, 17, 17, 14], "P": [30, 17, 17, 30, 16, 16, 16],
    "Q": [14, 17, 17, 17, 21, 18, 13], "R": [30, 17, 17, 30, 20, 18, 17],
    "S": [15, 16, 16, 14, 1, 1, 30], "T": [31, 4, 4, 4, 4, 4, 4],
    "U": [17, 17, 17, 17, 17, 17, 14], "V": [17, 17, 17, 17, 17, 10, 4],
    "W": [17, 17, 17, 21, 21, 21, 10], "X": [17, 17, 10, 4, 10, 17, 17],
    "Y": [17, 17, 10, 4, 4, 4, 4], "Z": [31, 1, 2, 4, 8, 16, 31],
    ":": [0, 12, 12, 0, 12, 12, 0], "-": [0, 0, 0, 14, 0, 0, 0],
    ".": [0, 0, 0, 0, 0, 12, 12], "/": [1, 1, 2, 4, 8, 16, 16],
    "@": [14, 17, 23, 21, 23, 16, 15], "'": [4, 4, 8, 0, 0, 0, 0],
    "(": [2, 4, 8, 8, 8, 4, 2], ")": [8, 4, 2, 2, 2, 4, 8],
    "#": [10, 10, 31, 10, 31, 10, 10], "+": [0, 4, 4, 31, 4, 4, 0],
    "!": [4, 4, 4, 4, 4, 0, 4], "?": [14, 17, 1, 2, 4, 0, 4],
    ",": [0, 0, 0, 0, 12, 4, 8], "%": [24, 25, 2, 4, 8, 19, 3],
    "*": [0, 4, 21, 14, 21, 4, 0], "=": [0, 0, 31, 0, 31, 0, 0],
    "<": [2, 4, 8, 16, 8, 4, 2], ">": [8, 4, 2, 1, 2, 4, 8],
    "&": [12, 18, 20, 8, 21, 18, 13], "°": [12, 18, 18, 12, 0, 0, 0],
}

# 7x7 colored icons, stored under private-use characters so they can sit in text.
PALETTE = {"y": (255, 200, 0), "w": (220, 220, 220), "b": (60, 140, 255),
           "c": (190, 225, 255), "g": (140, 140, 140)}
ICON_ROWS = {
    "sun":    ["y..y..y", ".y...y.", "..yyy..", "y.yyy.y", "..yyy..", ".y...y.", "y..y..y"],
    "partly": ["y.y....", ".yyy...", "yyy.ww.", ".y.wwww", "..wwwww", "..wwwww", "......."],
    "cloud":  [".......", "..www..", ".wwwww.", "wwwwwww", "wwwwwww", ".......", "......."],
    "rain":   ["..www..", ".wwwww.", "wwwwwww", ".......", ".b.b.b.", "b.b.b..", "......."],
    "snow":   ["..www..", ".wwwww.", "wwwwwww", ".......", ".c.c.c.", "..c.c..", ".c.c.c."],
    "storm":  ["..www..", ".wwwww.", "wwwwwww", "...y...", "..yy...", "...y...", "..y...."],
    "fog":    [".......", "ggggggg", ".......", ".gggggg", ".......", "ggggg..", "......."],
}
ICON_CHAR = {name: chr(0xE000 + i) for i, name in enumerate(ICON_ROWS)}
ICONS = {ICON_CHAR[name]: rows for name, rows in ICON_ROWS.items()}
SPACE_WIDTH = 3
GAP = 1        # blank columns between characters
HEIGHT = 7


def glyph_columns(ch):
    """List of columns for one character; each column is 7 booleans (top to bottom)."""
    rows = GLYPHS.get(ch.upper())
    if rows is None:
        return [[False] * HEIGHT for _ in range(SPACE_WIDTH)]
    used = [c for c in range(5) if any(r & (16 >> c) for r in rows)]
    lo, hi = min(used), max(used)
    return [[bool(r & (16 >> c)) for r in rows] for c in range(lo, hi + 1)]


def icon_columns(ch):
    """Columns of RGB-or-None for a colored icon character."""
    rows = ICONS[ch]
    return [[PALETTE.get(r[c]) for r in rows] for c in range(len(rows[0]))]


def text_width(text):
    return sum((len(icon_columns(ch)) if ch in ICONS else len(glyph_columns(ch))) + GAP
               for ch in text) - (GAP if text else 0)
