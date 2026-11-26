"""Sleeper fantasy football: your weekly matchup score, plus live point jumps.

Uses Sleeper's free public, read-only API (no login, no key): https://docs.sleeper.com
  user/<username> -> user_id;  user/<id>/leagues/nfl/<season>;  state/nfl -> current week
  league/<id>/rosters, /users, /matchups/<week> (live points per team and per player)
  players/nfl -> player names (big, so cached on disk and refreshed at most once a day)

The API reports points, not plays, so a live update says "ALLEN +6.4", not "TOUCHDOWN".
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from . import render, style
from .paths import DATA_DIR

API = "https://api.sleeper.app/v1/"
PLAYERS_FILE = os.path.join(DATA_DIR, "sleeper_players.json")
POLL_S = 30
BIG_PLAY = 3.0                       # alert when a starter gains this many points between polls
LABEL, ME, THEM = (40, 200, 220), (255, 200, 0), style.WHITE
UP, DOWN = (0, 220, 80), (255, 30, 30)

_cache, _lock = {}, threading.Lock()


def _get(path, ttl):
    """GET API+path as JSON, cached for ttl seconds."""
    with _lock:
        hit = _cache.get(path)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    req = urllib.request.Request(API + path, headers={"User-Agent": "matrix-ticker"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    with _lock:
        _cache[path] = (time.time(), data)
    return data


def clean(name, n=12):
    """Uppercase, only characters the panel font can draw, trimmed."""
    from .font import GLYPHS
    s = "".join(ch for ch in (name or "").upper() if ch == " " or (ch in GLYPHS and ord(ch) < 128))
    return re.sub(r"\s+", " ", s).strip()[:n].strip() or "?"


# ---------- players (names for live updates) ----------
_players, _players_lock = None, threading.Lock()


def players():
    """player_id -> short name. Cached on disk; downloads (a few MB) at most once a day."""
    global _players
    with _players_lock:
        if _players is not None and time.time() - _players[0] < 86400:
            return _players[1]
        try:
            fresh = time.time() - os.path.getmtime(PLAYERS_FILE) < 86400
        except OSError:
            fresh = False
        names = None
        if fresh:
            try:
                with open(PLAYERS_FILE) as f:
                    names = json.load(f)
            except (OSError, ValueError):
                names = None
        if names is None:
            raw = _get("players/nfl", 86400)
            names = {}
            for pid, p in raw.items():
                if p.get("position") == "DEF" or pid.isalpha():
                    names[pid] = f"{pid} D/ST"
                else:
                    last = p.get("last_name") or p.get("full_name") or pid
                    names[pid] = f"{(p.get('first_name') or ' ')[0]}. {last}".strip(". ")
            try:
                with open(PLAYERS_FILE, "w") as f:
                    json.dump(names, f)
            except OSError:
                pass
        _players = (time.time(), names)
        return names


def player_name(pid):
    try:
        return clean(players().get(pid, pid), 14)
    except Exception:
        return clean(pid, 14)


# ---------- matchups ----------
def state():
    return _get("state/nfl", 600)


def user_id(username):
    u = _get(f"user/{urllib.parse.quote(username.strip())}", 86400)
    if not u:
        raise ValueError(f"no Sleeper user called {username!r}")
    return u["user_id"]


def leagues(username):
    st = state()
    return _get(f"user/{user_id(username)}/leagues/nfl/{st['season']}", 3600) or []


def _team_names(league_id):
    users = {u["user_id"]: (u.get("metadata") or {}).get("team_name") or u.get("display_name")
             for u in _get(f"league/{league_id}/users", 3600) or []}
    rosters = _get(f"league/{league_id}/rosters", 3600) or []
    return {r["roster_id"]: users.get(r.get("owner_id"), f"TEAM {r['roster_id']}") for r in rosters}, rosters


def matchups(username, league_filter="", ttl=30):
    """Your matchup in each league (or only leagues whose name contains league_filter).
    Yields dicts: league, me, them, my_points, their_points, my_players, their_players
    (players: {player_id: points} for starters)."""
    st = state()
    if st.get("season_type") not in ("regular", "post"):
        return
    week = st.get("week") or st.get("display_week")
    uid = user_id(username)
    for lg in leagues(username):
        if league_filter and league_filter.lower() not in (lg.get("name") or "").lower():
            continue
        names, rosters = _team_names(lg["league_id"])
        mine = next((r for r in rosters if r.get("owner_id") == uid or uid in (r.get("co_owners") or [])), None)
        if not mine:
            continue
        ms = _get(f"league/{lg['league_id']}/matchups/{week}", ttl) or []
        me = next((m for m in ms if m["roster_id"] == mine["roster_id"]), None)
        if not me:
            continue
        them = next((m for m in ms if m.get("matchup_id") is not None and m["matchup_id"] == me.get("matchup_id")
                     and m["roster_id"] != me["roster_id"]), None)

        def starters(m):
            pts = m.get("players_points") or {}
            return {p: pts.get(p, 0.0) for p in m.get("starters") or [] if p and p != "0"}
        yield {
            "league": clean(lg.get("name"), 14), "league_id": lg["league_id"],
            "me": clean(names.get(me["roster_id"]), 16), "them": clean(names.get(them["roster_id"]), 16) if them else "BYE",
            "my_points": me.get("custom_points") or me.get("points") or 0.0,
            "their_points": (them.get("custom_points") or them.get("points") or 0.0) if them else 0.0,
            "my_players": starters(me), "their_players": starters(them) if them else {},
        }


def segments(ms):
    """Scrolling line: FANTASY : MY TEAM 87.4 - 92.1 THEM   (one entry per league).
    ms: list of matchups() results."""
    if not ms:
        return None
    segs = [("FANTASY", LABEL), (" : ", style.GRAY)]
    for i, m in enumerate(ms):
        if i:
            segs.append(("     ", style.WHITE))
        if len(ms) > 1:
            segs += [(m["league"], style.GRAY), (" ", style.WHITE)]
        mine, theirs = m["my_points"], m["their_points"]
        color = UP if mine > theirs else DOWN if mine < theirs else style.WHITE
        segs += [(m["me"], ME), (" ", style.WHITE), (f"{mine:.1f}", color), (" - ", style.GRAY),
                 (f"{theirs:.1f}", style.WHITE), (" ", style.WHITE), (m["them"], THEM)]
    return segs


def fit(name, tail):
    """'J. SMITH-NJIGBA +6.4' if it fits the panel, else drop the initial, else trim the name."""
    for n in (name, name.split(". ", 1)[-1]):
        if len(render.strip([(n + tail, style.WHITE)])) <= render.W:
            return n + tail
    while n and len(render.strip([(n + tail, style.WHITE)])) > render.W:
        n = n[:-1]
    return n.rstrip(" .-") + tail


class Watcher(threading.Thread):
    """Polls your matchups and calls on_alert(Alert) when a starter jumps BIG_PLAY+ points."""

    def __init__(self, settings, on_alert, stop_event, log=print, interval=POLL_S, source=None):
        super().__init__(daemon=True)
        self.s, self.on_alert, self.stop, self.log, self.interval = settings, on_alert, stop_event, log, interval
        self.source = source or (lambda u, lg: list(matchups(u, lg, ttl=self.interval / 2)))
        self.prev = {}

    def poll(self):
        from .alerts import Alert          # avoid an import cycle
        if not self.s.sleeper_user.strip() or "FANTASY" not in self.s.leagues or not self.s.alerts:
            return
        try:
            ms = self.source(self.s.sleeper_user, self.s.sleeper_league)
        except Exception:
            return                         # offline or Sleeper hiccup; try next poll
        for m in ms:
            for side, color in (("my_players", UP), ("their_players", DOWN)):
                for pid, pts in m[side].items():
                    k = (m["league_id"], side, pid)
                    before = self.prev.get(k)
                    self.prev[k] = pts
                    if before is None or pts - before < BIG_PLAY:
                        continue
                    word = fit(player_name(pid), f" +{pts - before:.1f}")
                    score = [(m["me"][:6], ME), (f" {m['my_points']:.1f}", style.WHITE), ("-", style.GRAY),
                             (f"{m['their_points']:.1f} ", style.WHITE), (m["them"][:6], THEM)]
                    if len(render.strip(score)) > render.W:
                        score = [(f"{m['my_points']:.1f} - {m['their_points']:.1f}", style.WHITE)]
                    whose = "" if side == "my_players" else f"{m['them']}: "
                    self.on_alert(Alert(word, color, lines=([(word, color)], score),
                                        log_text=f"Fantasy: {whose}{word} ({m['my_points']:.1f}-{m['their_points']:.1f})"))

    def run(self):
        while not self.stop.is_set():
            self.poll()
            end = time.time() + self.interval
            while time.time() < end and not self.stop.is_set():
                time.sleep(0.5)
