"""Static full-screen widgets (dashboard, calendar, counter) and the now-playing line."""
import datetime as dt

from . import font, media, style, system
from .canvas import Canvas, W, big_width, normal_width, small_width

WHITE, GRAY, DIM = (255, 255, 255), (110, 110, 110), (28, 30, 38)
CYAN, GOLD, RED = (60, 210, 230), (255, 200, 0), (220, 35, 35)
METER = [(70, 230, 220), (60, 190, 235), (60, 150, 245), (70, 110, 255), (95, 80, 255)]
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


def _meter(c, x, y, w, h, frac):
    """NexLinq-style bar: lit columns fade teal -> blue, the rest stay dim."""
    lit = round(max(0.0, min(1.0, frac)) * w)
    for i in range(w):
        color = METER[min(len(METER) - 1, i * len(METER) // w)] if i < lit else DIM
        for yy in range(y, y + h):
            c.set(x + i, yy, color)


def _clock_text(now, h24):
    return now.strftime("%H:%M") if h24 else f"{now.hour % 12 or 12}:{now.minute:02d}"


def dashboard(now=None, h24=False):
    """CPU / GPU meters, big clock, date: a remake of NexLinq's widget.
    CPU meter = CPU load. GPU meter = GPU temperature (30-90 C) on NVIDIA, else GPU load."""
    now = now or dt.datetime.now()
    c = Canvas()
    cpu = system.cpu_load()
    gtemp = system.gpu_temp()
    gpu = (gtemp - 30) / 60 if gtemp is not None else (system.gpu_load() or 0) / 100
    c.small("CPU", 0, 0, WHITE)
    c.small("GPU", 0, 5, WHITE)
    _meter(c, 12, 0, 15, 4, (cpu or 0) / 100)
    _meter(c, 12, 5, 15, 4, gpu)
    month, day = MONTHS[now.month - 1], str(now.day)
    date_w = normal_width(month) + 1 + normal_width(day)
    date_x = W - date_w
    x = c.normal(month, date_x, 1, WHITE)
    c.normal(day, x + 2, 1, CYAN)
    clock = _clock_text(now, h24)
    left, right = 28, date_x - 2                       # center the clock in the gap
    c.big(clock, left + max(0, (right - left - big_width(clock)) // 2), WHITE)
    return c.to_bytes()


def calendar(today=None):
    """A tear-off calendar page (month + day) and this week with today highlighted."""
    today = today or dt.date.today()
    c = Canvas()
    c.rect(0, 0, 20, 4, (150, 20, 20))                 # page header (deep red)
    m = MONTHS[today.month - 1]
    c.small(m, (21 - small_width(m)) // 2, 0, WHITE)
    for yy in range(5, 10):                            # page outline under the header
        c.set(0, yy, (90, 90, 90))
        c.set(20, yy, (90, 90, 90))
    d = str(today.day)
    c.small(d, (21 - small_width(d)) // 2, 5, WHITE)
    start = today - dt.timedelta(days=(today.weekday() + 1) % 7)   # week starts Sunday
    for i in range(7):
        day = start + dt.timedelta(days=i)
        x0 = 24 + i * 9
        weekend = i in (0, 6)
        if day == today:
            c.rect(x0 - 1, 5, x0 + 7, 9, RED)
        c.small("SMTWTFS"[i], x0 + 2, 0, CYAN if day == today else (GRAY if weekend else (190, 190, 190)))
        num = str(day.day)
        color = WHITE if day == today else ((130, 130, 130) if weekend else (215, 215, 215))
        c.small(num, x0 + (7 - small_width(num)) // 2, 5, color)
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
