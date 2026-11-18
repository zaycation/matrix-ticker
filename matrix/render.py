"""Turn colored text into 90x10 frames for the panel (and a terminal preview).

A "strip" is a list of columns; each column is 10 RGB tuples (top to bottom).
The panel's pixel order is rows of 90, left to right, starting top-left.
"""
from . import font

W, H = 90, 10
TOP = 1                      # 7-px glyphs drawn on rows 1-7
BLACK = (0, 0, 0)


def strip(segments):
    """segments: [(text, (r, g, b)), ...] -> list of columns."""
    cols = []
    for text, rgb in segments:
        for ch in text:
            if ch in font.ICONS:                      # multi-colored icon, ignores rgb
                for icol in font.icon_columns(ch):
                    col = [BLACK] * H
                    for y, c in enumerate(icol):
                        if c:
                            col[TOP + y] = c
                    cols.append(col)
                cols.extend([[BLACK] * H for _ in range(font.GAP)])
                continue
            for gcol in font.glyph_columns(ch):
                col = [BLACK] * H
                for y, on in enumerate(gcol):
                    if on:
                        col[TOP + y] = rgb
                cols.append(col)
            cols.extend([[BLACK] * H for _ in range(font.GAP)])
    return cols


def width(segments):
    return len(strip(segments))


def frame(cols, offset=0):
    """90x10 window of a strip. offset = strip column shown at the panel's left edge
    (negative = the strip starts further right)."""
    buf = bytearray(W * H * 3)
    for x in range(W):
        c = x + offset
        if 0 <= c < len(cols):
            for y, (r, g, b) in enumerate(cols[c]):
                i = (y * W + x) * 3
                buf[i:i + 3] = bytes((r, g, b))
    return bytes(buf)


def centered(segments):
    """Frame with the segments centered (cropped if wider than the panel)."""
    cols = strip(segments)
    return frame(cols, -max(0, (W - len(cols)) // 2) if len(cols) <= W else 0)


def preview(buf):
    """Print a frame in a truecolor terminal (2 characters per LED)."""
    out = ["\x1b[H"]
    for y in range(H):
        for x in range(W):
            i = (y * W + x) * 3
            r, g, b = buf[i], buf[i + 1], buf[i + 2]
            out.append(f"\x1b[48;2;{r};{g};{b}m " if (r or g or b) else "\x1b[48;2;20;20;20m ")
        out.append("\x1b[0m\n")
    print("".join(out), end="", flush=True)
