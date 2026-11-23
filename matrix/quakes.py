"""Earthquake alerts near you, from the USGS live feed (free, no key).

Every minute: quakes of magnitude 2.5+ from the past hour
(https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php), kept only if they're within
`radius` miles of your weather location and at least MIN_MAG. Each one cuts in once:
QUAKE M4.1, then how far and which way (18 MI NW).
"""
import json
import math
import threading
import time
import urllib.request

from . import style, weather

FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_hour.geojson"
MIN_MAG = 3.5                 # smaller ones happen around LA most weeks and are rarely felt
MAX_AGE_S = 30 * 60           # don't alert on quakes older than this
ORANGE, RED = (255, 140, 0), (255, 30, 30)


def miles(lat1, lon1, lat2, lon2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def direction(lat1, lon1, lat2, lon2):
    """Compass direction from point 1 to point 2: N, NE, E, ..."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    deg = (math.degrees(math.atan2(x, y)) + 360) % 360
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round(deg / 45) % 8]


def fetch():
    req = urllib.request.Request(FEED, headers={"User-Agent": "matrix-ticker"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def nearby(feed, lat, lon, radius, min_mag=MIN_MAG, now=None):
    """[(id, mag, miles, direction, title)] for recent quakes close enough, strongest first."""
    now = now or time.time()
    out = []
    for f in feed.get("features", []):
        p, g = f.get("properties") or {}, (f.get("geometry") or {}).get("coordinates") or []
        mag = p.get("mag")
        if mag is None or mag < min_mag or len(g) < 2 or now - (p.get("time") or 0) / 1000 > MAX_AGE_S:
            continue
        d = miles(lat, lon, g[1], g[0])
        if d <= radius:
            out.append((f.get("id"), mag, d, direction(lat, lon, g[1], g[0]), p.get("title") or p.get("place") or ""))
    return sorted(out, key=lambda q: -q[1])


class Watcher(threading.Thread):
    def __init__(self, settings, on_alert, stop_event, log=print, interval=60):
        super().__init__(daemon=True)
        self.s, self.on_alert, self.stop, self.log, self.interval = settings, on_alert, stop_event, log, interval
        self.seen = set()

    def poll(self, feed=None, now=None):
        from .alerts import Alert
        if not self.s.quake_alerts or not self.s.location.strip():
            return
        try:
            lat, lon, _ = weather.locate(self.s.location)
            feed = feed if feed is not None else fetch()
        except Exception:
            return
        for qid, mag, d, way, title in nearby(feed, lat, lon, self.s.quake_radius, now=now):
            if qid in self.seen:
                continue
            self.seen.add(qid)
            color = RED if mag >= 5 else ORANGE
            where = "NEARBY" if d < 1 else f"{d:.0f} MI {way}"
            self.on_alert(Alert(f"QUAKE M{mag:.1f}", color,
                                lines=([(f"QUAKE M{mag:.1f}", color)], [(where, style.WHITE)]),
                                log_text=f"Earthquake: {title} ({d:.0f} mi {way})"))

    def run(self):
        while not self.stop.is_set():
            self.poll()
            end = time.time() + self.interval
            while time.time() < end and not self.stop.is_set():
                time.sleep(0.5)
