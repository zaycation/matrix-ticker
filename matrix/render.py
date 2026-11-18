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


_last_size = None


def preview_scale():
    """(chars per LED across, rows per LED down) to fill the terminal width.
    Terminal cells are about twice as tall as wide, so rows scale half as much."""
    import shutil
    cols = shutil.get_terminal_size((90, 24)).columns
    kx = max(1, cols // W)
    return kx, max(1, kx // 2)


def preview_rows():
    """Terminal rows the preview uses (messages go below this)."""
    return H * preview_scale()[1]


def preview(buf):
    """Draw a frame in a truecolor terminal, scaled to the window width.
    At larger sizes each LED gets a dark edge so it looks like the panel."""
    global _last_size
    kx, ky = preview_scale()
    out = []
    if (kx, ky) != _last_size:          # window resized: clear leftovers
        out.append("\x1b[2J")
        _last_size = (kx, ky)
    out.append("\x1b[H")
    off = "\x1b[48;2;20;20;20m"
    gap = "\x1b[48;2;8;8;8m"
    for y in range(H):
        for sub in range(ky):
            line = []
            edge_row = ky >= 2 and sub == ky - 1
            for x in range(W):
                i = (y * W + x) * 3
                r, g, b = buf[i], buf[i + 1], buf[i + 2]
                color = f"\x1b[48;2;{r};{g};{b}m" if (r or g or b) else off
                if edge_row:
                    line.append(gap + " " * kx)
                elif kx >= 3:
                    line.append(color + " " * (kx - 1) + gap + " ")
                else:
                    line.append(color + " " * kx)
            out.append("".join(line) + "\x1b[0m\n")
    print("".join(out), end="", flush=True)
