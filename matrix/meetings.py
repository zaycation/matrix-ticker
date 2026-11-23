"""Upcoming meetings from a calendar's private iCal link (no Google login needed).

Google Calendar: Settings -> pick your calendar -> "Secret address in iCal format".
(Outlook and Apple Calendar have similar "publish"/"share" links; any .ics URL works.)

Only meetings starting within the next `window` minutes show in the ticker, plus ones that
started in the last few minutes ("NOW"). All-day events, cancelled ones, and ones you
declined are skipped. A reminder cuts in `alert_min` minutes before each meeting.
"""
import datetime as dt
import threading
import time
import urllib.request

from . import style
from .font import ICON_CHAR
from .sleeper import clean

FETCH_TTL = 300                  # re-download the calendar every 5 minutes
NOW_GRACE = 5                    # keep showing a meeting this many minutes after it starts
LABEL = (66, 133, 244)           # Google blue
SOON, NOW = (255, 200, 0), (255, 30, 30)

_cache, _lock = {}, threading.Lock()


def _download(url):
    url = url.strip()
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    with _lock:
        hit = _cache.get(url)
        if hit and time.time() - hit[0] < FETCH_TTL:
            return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": "matrix-ticker"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read()
    with _lock:
        _cache[url] = (time.time(), data)
    return data


def _declined(ev, owner):
    if not owner:
        return False
    for a in ev.get("ATTENDEE", []) if isinstance(ev.get("ATTENDEE"), list) else [ev.get("ATTENDEE")]:
        if a is not None and str(a).lower().replace("mailto:", "") == owner:
            return str(a.params.get("PARTSTAT", "")).upper() == "DECLINED"
    return False


def upcoming(url, window=90, now=None, ics=None):
    """[(start, title)] for meetings starting within `window` minutes (or started < NOW_GRACE ago),
    soonest first. start is a local, timezone-aware datetime."""
    import icalendar
    import recurring_ical_events
    now = now or dt.datetime.now().astimezone()
    cal = icalendar.Calendar.from_ical(ics if ics is not None else _download(url))
    owner = str(cal.get("X-WR-CALNAME", "")).lower()          # Google: the calendar's email address
    owner = owner if "@" in owner else ""
    out = []
    for ev in recurring_ical_events.of(cal).between(now - dt.timedelta(minutes=NOW_GRACE),
                                                   now + dt.timedelta(minutes=window)):
        start = ev.get("DTSTART").dt
        if not isinstance(start, dt.datetime):                     # all-day
            continue
        if str(ev.get("STATUS", "")).upper() == "CANCELLED" or _declined(ev, owner):
            continue
        start = start.astimezone() if start.tzinfo else start.replace(tzinfo=now.tzinfo)
        if not (now - dt.timedelta(minutes=NOW_GRACE) <= start <= now + dt.timedelta(minutes=window)):
            continue
        out.append((start, clean(str(ev.get("SUMMARY", "")) or "MEETING", 28)))
    return sorted(set(out))


def until(start, now=None):
    """'NOW', 'IN 5 MIN', 'IN 1 HR 20 MIN'."""
    now = now or dt.datetime.now().astimezone()
    mins = int(-(-(start - now).total_seconds() // 60))        # round up
    if mins <= 0:
        return "NOW"
    h, m = divmod(mins, 60)
    return f"IN {h} HR {m} MIN" if h and m else f"IN {h} HR" if h else f"IN {m} MIN"


def clock(t, h24=False):
    return t.strftime("%H:%M") if h24 else t.strftime("%I:%M %p").lstrip("0")


def segments(url, window=90, h24=False, now=None, ics=None):
    """Scrolling line: [cal] STANDUP IN 25 MIN 10:30 AM   1:1 WITH NOAH IN 1 HR 11:30 AM"""
    now = now or dt.datetime.now().astimezone()
    items = upcoming(url, window, now, ics)
    if not items:
        return None
    segs = [(ICON_CHAR["cal"], None), ("  ", style.WHITE)]
    for i, (start, title) in enumerate(items):
        if i:
            segs.append(("     ", style.WHITE))
        when = until(start, now)
        color = NOW if when == "NOW" else SOON if (start - now) <= dt.timedelta(minutes=10) else style.WHITE
        segs += [(title, style.WHITE), (" ", style.WHITE), (when, color), (" ", style.WHITE),
                 (clock(start, h24), style.GRAY)]
    return segs


class Watcher(threading.Thread):
    """Calls on_alert(Alert) `alert_min` minutes before each meeting (once per meeting)."""

    def __init__(self, settings, on_alert, stop_event, log=print, interval=30):
        super().__init__(daemon=True)
        self.s, self.on_alert, self.stop, self.log, self.interval = settings, on_alert, stop_event, log, interval
        self.done = set()

    def poll(self, now=None, ics=None):
        from .alerts import Alert
        from . import render
        if not self.s.calendar_url.strip() or "MEETINGS" not in self.s.leagues or not self.s.meeting_alert:
            return
        now = now or dt.datetime.now().astimezone()
        try:
            items = upcoming(self.s.calendar_url, self.s.meeting_alert, now, ics)
        except Exception:
            return
        for start, title in items:
            if start < now or (start, title) in self.done:
                continue
            self.done.add((start, title))
            name = title
            while len(render.strip([(name, style.WHITE)])) > render.W:
                name = name[:-1]
            when = until(start, now)
            self.on_alert(Alert(name.rstrip(" .-"), SOON,
                                lines=([(ICON_CHAR["cal"], None), ("  " + when, SOON)], [(name.rstrip(" .-"), style.WHITE)]),
                                log_text=f"Meeting: {title} {when.lower()}"))

    def run(self):
        while not self.stop.is_set():
            self.poll()
            end = time.time() + self.interval
            while time.time() < end and not self.stop.is_set():
                time.sleep(0.5)
