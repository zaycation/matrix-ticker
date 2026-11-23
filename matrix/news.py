"""Sports headlines from ESPN's public news JSON (same unofficial source as the scores).

site.api.espn.com/apis/site/v2/sports/<sport>/<league>/news -> {"articles": [{"headline",
"published", "type", "categories": [{"type": "team", "description": "Chicago Bears"}, ...]}]}

- NEWS item: the latest headlines from the leagues you show, scrolling in the cycle.
- Breaking alerts: new headlines cut in, scrolling once. "all" = any league you show (at most
  one every NEWS_GAP_S so it doesn't take over); "mine" = only headlines about favorite teams
  (no limit); "off".
"""
import datetime as dt
import json
import threading
import time
import urllib.request

from . import favorites, scores, style
from .sleeper import clean

URL = "https://site.api.espn.com/apis/site/v2/sports/{}/news"
PATHS = {**scores.TEAM_LEAGUES, **scores.TENNIS_TOURS}
TTL_S = 300                     # re-download each league's headlines every 5 minutes
MAX_AGE_H = 12                  # NEWS item: headlines from the last 12 hours
NEWS_GAP_S = 10 * 60            # "all" alerts: at most one per 10 minutes
SKIP_TYPES = {"Media", "Video"}
LABEL, BREAKING = (255, 60, 60), (255, 60, 60)

_cache, _lock = {}, threading.Lock()


def _published(a):
    try:
        return dt.datetime.fromisoformat(a.get("published", "").replace("Z", "+00:00"))
    except ValueError:
        return None


def headlines(league):
    """[{id, league, headline, when, teams}] newest first."""
    path = PATHS.get(league)
    if not path:
        return []
    with _lock:
        hit = _cache.get(league)
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
    req = urllib.request.Request(URL.format(path), headers={"User-Agent": "matrix-ticker"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    out = []
    for a in data.get("articles", []):
        when = _published(a)
        if not a.get("headline") or when is None or a.get("type") in SKIP_TYPES:
            continue
        teams = [c.get("description", "") for c in a.get("categories") or [] if c.get("type") == "team"]
        out.append({"id": a.get("id") or a["headline"], "league": league, "headline": clean(a["headline"], 120),
                    "when": when, "teams": teams})
    out.sort(key=lambda h: h["when"], reverse=True)
    with _lock:
        _cache[league] = (time.time(), out)
    return out


def about_favorite(h, terms):
    if not terms:
        return False
    text = " ".join([h["headline"]] + h["teams"])
    return any(favorites.matches([t], "", text) for t in terms)


def segments(leagues, terms=(), limit=6, now=None):
    """NEWS : NFL  HEADLINE   NBA  HEADLINE ...  (favorite-team headlines first, starred)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    items = []
    for lg in leagues:
        if lg not in PATHS:
            continue
        try:
            items += [h for h in headlines(lg) if now - h["when"] <= dt.timedelta(hours=MAX_AGE_H)]
        except Exception:
            continue
    if not items:
        return None
    items.sort(key=lambda h: (not about_favorite(h, terms), -h["when"].timestamp()))
    from .font import ICON_CHAR
    segs = [("NEWS", LABEL), (" : ", style.GRAY)]
    for i, h in enumerate(items[:limit]):
        if i:
            segs.append(("     ", style.WHITE))
        if about_favorite(h, terms):
            segs += [(ICON_CHAR["star"], None), (" ", style.WHITE)]
        segs += [(h["league"], style.GRAY), ("  ", style.WHITE), (h["headline"], style.WHITE)]
    return segs


class Watcher(threading.Thread):
    """Cuts in with new headlines (mode "all" or "mine"). The first poll is only a baseline."""

    def __init__(self, settings, on_alert, stop_event, log=print, interval=120):
        super().__init__(daemon=True)
        self.s, self.on_alert, self.stop, self.log, self.interval = settings, on_alert, stop_event, log, interval
        self.seen, self.primed, self.last_all = set(), set(), 0.0

    def poll(self, now=None):
        from .alerts import Alert
        mode = self.s.news_alerts
        if mode not in ("all", "mine"):
            return
        terms = favorites.parse(self.s.favorites)
        now_t = now or time.time()
        for lg in [x for x in self.s.leagues if x in PATHS]:
            try:
                hs = headlines(lg)
            except Exception:
                continue
            first = lg not in self.primed
            self.primed.add(lg)
            for h in reversed(hs):                         # oldest new one first
                if h["id"] in self.seen:
                    continue
                self.seen.add(h["id"])
                if first:
                    continue                               # baseline: don't replay old news
                mine = about_favorite(h, terms)
                if mode == "mine" and not mine:
                    continue
                if not mine and now_t - self.last_all < NEWS_GAP_S:
                    continue                               # still shows in the NEWS item
                if not mine:
                    self.last_all = now_t
                from .font import ICON_CHAR
                lead = [(ICON_CHAR["star"], None), (" ", style.WHITE)] if mine else []
                self.on_alert(Alert("BREAKING", BREAKING, log_text=f"News: {h['league']} {h['headline']}",
                                    scroll=lead + [("BREAKING", BREAKING), ("  ", style.WHITE), (h["league"], style.GRAY),
                                                   ("  ", style.WHITE), (h["headline"], style.WHITE)]))

    def run(self):
        while not self.stop.is_set():
            self.poll()
            end = time.time() + self.interval
            while time.time() < end and not self.stop.is_set():
                time.sleep(0.5)
