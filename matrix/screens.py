"""Static full-screen widgets (dashboard, calendar, counter) and the now-playing line."""
import datetime as dt
import time

from . import network, font, media, style, system
from .canvas import Canvas, W, big_width, normal_width, small_width

WHITE, GRAY, DIM = (255, 255, 255), (110, 110, 110), (28, 30, 38)
CYAN, GOLD, RED = (60, 210, 230), (255, 200, 0), (220, 35, 35)
METER = [(70, 230, 220), (60, 190, 235), (60, 150, 245), (70, 110, 255), (95, 80, 255)]
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
WEEKDAYS = "MON TUE WED THU FRI SAT SUN".split()
WEEK_DIM = (70, 70, 70)


def _meter(c, x, y, w, h, frac):
    """NexLinq-style bar: lit columns fade teal -> blue, the rest stay dim."""
    lit = round(max(0.0, min(1.0, frac)) * w)
    for i in range(w):
        color = METER[min(len(METER) - 1, i * len(METER) // w)] if i < lit else DIM
        for yy in range(y, y + h):
            c.set(x + i, yy, color)


def _clock_text(now, h24):
    return now.strftime("%H:%M") if h24 else f"{now.hour % 12 or 12}:{now.minute:02d}"


CORNER_SWAP_S = 4                      # "both": switch between date and ping this often
CORNER_W = 32                          # right-hand corner width, so the clock never shifts


def _ping_corner(c):
    """'14MS' (green / gold / red by quality) or 'DOWN' in red. False if no reading yet."""
    ms = network.ping()
    if ms is None and not network.started():
        return False
    if ms is None:
        text, color = "DOWN", RED
    else:
        text = f"{ms:.0f}"
        color = (37, 200, 100) if ms < network.GOOD_MS else GOLD if ms < network.OK_MS else RED
    unit = "" if ms is None else "MS"
    w = normal_width(text) + (1 + normal_width(unit) if unit else 0)
    x = c.normal(text, W - w, 1, color)
    if unit:
        c.normal(unit, x + 2, 1, WHITE)
    return True


def _date_corner(c, now):
    month, day = MONTHS[now.month - 1], str(now.day)
    x = c.normal(month, W - (normal_width(month) + 1 + normal_width(day)), 1, WHITE)
    c.normal(day, x + 2, 1, CYAN)


def dashboard(now=None, h24=False, cpu_meter="load", gpu_meter="temp", corner="both"):
    """CPU / GPU meters, big clock, and a corner with the date, ping, or both taking turns.
    Meters: see system.CPU_METERS / GPU_METERS (GPU ones need an NVIDIA card)."""
    now = now or dt.datetime.now()
    c = Canvas()
    top_label, top = system.CPU_METERS.get(cpu_meter, system.CPU_METERS["load"])
    bottom_label, bottom = system.GPU_METERS.get(gpu_meter, system.GPU_METERS["temp"])
    c.tiny(top_label, 0, 0, WHITE)                      # rows 0-3
    c.tiny(bottom_label, 0, 6, WHITE)                   # rows 6-9 (2-row gap between)
    _meter(c, 12, 0, 15, 4, top() or 0)
    _meter(c, 12, 6, 15, 4, bottom() or 0)
    show_ping = corner == "ping" or (corner == "both" and int(time.time() // CORNER_SWAP_S) % 2 == 1)
    if not (show_ping and _ping_corner(c)):
        _date_corner(c, now)
    clock = _clock_text(now, h24)
    left, right = 28, W - CORNER_W - 2                  # center the clock in the gap
    c.big(clock, left + max(0, (right - left - big_width(clock)) // 2), WHITE)
    return c.to_bytes()


def calendar(today=None):
    """Minimal: weekday + date centered, and a thin week bar underneath (today lit).
    Bright, solid colors only: dim grays and tiny 3x5 digits look muddy on the real LEDs."""
    today = today or dt.date.today()
    c = Canvas()
    wd = WEEKDAYS[today.weekday()]
    date = f"{MONTHS[today.month - 1]} {today.day}"
    w = normal_width(wd) + 5 + normal_width(date)
    x = (W - w) // 2
    x = c.normal(wd, x, 0, RED)
    c.normal(date, x + 5, 0, WHITE)
    sunday_index = (today.weekday() + 1) % 7            # week runs Sunday..Saturday
    seg, gap = 10, 3
    x0 = (W - (7 * seg + 6 * gap)) // 2
    for i in range(7):
        color = RED if i == sunday_index else WEEK_DIM
        c.rect(x0 + i * (seg + gap), 9, x0 + i * (seg + gap) + seg - 1, 9, color)
    return c.to_bytes()


def counter(label, count, flash=False, blink=False):
    """Label + big count. While flashing (just bumped), the number blinks and shows +1."""
    c = Canvas()
    label = label.upper()[:10] or "COUNT"
    c.normal(label, 0, 1, CYAN)
    num = str(count)
    color = WHITE if (flash and blink) else GOLD
    x = W - big_width(num)
    c.big(num, x, color)
    if flash:
        c.small("+1", x - small_width("+1") - 2, 0, (37, 184, 100))
    return c.to_bytes()


def timer(label, remaining, progress, paused=False, blink=False):
    """Label + big countdown, with a bar along the bottom that drains as time runs out.
    Paused: the time goes gray and the label says PAUSED (blinking)."""
    from .timer import clock
    c = Canvas()
    text = clock(remaining)
    color = GRAY if paused else (RED if remaining <= 60 else WHITE)
    x = W - big_width(text)
    c.big(text, x, color, top=0, height=8)
    name = "PAUSED" if paused and blink else (label.upper()[:10] or "TIMER")
    room = x - 3
    while name and normal_width(name) > room:
        name = name[:-1]
    c.normal(name, 0, 0, GOLD if name == "PAUSED" else CYAN)
    lit = round(max(0.0, min(1.0, progress)) * W)
    c.rect(0, 9, W - 1, 9, DIM)
    if lit:
        c.rect(0, 9, lit - 1, 9, RED if remaining <= 60 else (60, 190, 235))
    return c.to_bytes()


def times_up(label, blink):
    """TIME'S UP, blinking red and white."""
    c = Canvas()
    msg = "TIME'S UP"
    c.normal(msg, (W - normal_width(msg)) // 2, 1, RED if blink else WHITE)
    if blink:
        c.rect(0, 9, W - 1, 9, RED)
    return c.to_bytes()


def now_playing_segments():
    """Scrolling 'note TITLE - ARTIST', or None if nothing is playing."""
    np = media.now_playing()
    if not np:
        return None
    title, artist = np
    segs = [(font.ICON_CHAR["note"], None), ("  " + title.upper(), WHITE)]
    if artist:
        segs += [("  -  ", style.GRAY), (artist.upper(), CYAN)]
    return segs
