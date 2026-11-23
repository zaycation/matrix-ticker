"""Big-moment alerts for favorite teams.

A background watcher polls the scores every 30 s and compares each favorite-team game
with the last poll. Alerts:
  start      game goes live            KICKOFF / TIP-OFF / FIRST PITCH / MATCH START
  scoring    favorite scores           NFL: TOUCHDOWN, FIELD GOAL, 2 POINTS; MLB: RUN SCORES / 2 RUNS
             (basketball scores too often to alert on every basket)
  close      late and close, once      CLOSE GAME (NFL/basketball last period within 8/5, MLB 9th+ within 1)
  final      game ends                 WIN! (green) or FINAL
The first poll only takes a baseline, so starting mid-game doesn't fire a burst of alerts.
"""
import threading
import time
from dataclasses import dataclass

from . import favorites, render, scores, style
from .font import ICON_CHAR

POLL_S = 30
LAST_PERIOD = {"NFL": 4, "NBA": 4, "WNBA": 4, "NCAAW": 4, "MLB": 9}
CLOSE_MARGIN = {"NFL": 8, "NBA": 5, "WNBA": 5, "NCAAW": 5, "MLB": 1}
START_WORD = {"NFL": "KICKOFF", "MLB": "FIRST PITCH", "ATP": "MATCH START", "WTA": "MATCH START"}
GOLD, WIN_GREEN = (255, 200, 0), (0, 220, 80)


@dataclass
class Alert:
    word: str              # e.g. "TOUCHDOWN"
    color: tuple           # color of the word
    game: dict = None      # the game as it is now (score alerts)
    lines: tuple = None    # or: ready-made screens, each a list of (text, rgb) segments
    log_text: str = None
    scroll: list = None    # or: segments that scroll across once (long text, e.g. a headline)

    def text(self):
        return self.log_text or f"{self.word}: {score_line(self.game)}"


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def score_line(g):
    if g.get("tennis"):
        return f"{g['away']} V {g['home']} {g.get('sets', '')}".strip()
    if g["state"] == "pre":
        return f"{g['away']} @ {g['home']}"
    return f"{g['away']} {g['away_score']}-{g['home_score']} {g['home']}"


def _key(g):
    return (g.get("league"), g.get("id") or f"{g.get('away')}-{g.get('home')}")


def _scoring_word(league, delta):
    if league == "NFL":
        if delta >= 6:
            return "TOUCHDOWN"
        return {3: "FIELD GOAL", 2: "2 POINTS", 1: None}.get(delta, "SCORE")   # 1 = extra point: skip
    if league == "MLB":
        return "RUN SCORES" if delta == 1 else f"{delta} RUNS"
    return None


def diff(old, new, terms, closed):
    """Alerts for one favorite game between two polls. closed: set of game keys that
    already got CLOSE GAME (updated here)."""
    out = []
    fav = favorites.side(new, terms)
    if not fav or old is None:
        return out
    league = new.get("league")
    team_color = style.team_colors(new)[0 if fav == "away" else 1]
    if old["state"] == "pre" and new["state"] == "in":
        out.append(Alert(START_WORD.get(league, "TIP-OFF"), team_color, new))
    if new["state"] in ("in", "post"):
        before, now = _int(old.get(f"{fav}_score")), _int(new.get(f"{fav}_score"))
        if before is not None and now is not None and now > before:
            word = _scoring_word(league, now - before)
            if word:
                out.append(Alert(word, team_color, new))
    if new["state"] == "in" and _key(new) not in closed and league in LAST_PERIOD:
        a, h = _int(new.get("away_score")), _int(new.get("home_score"))
        if (a is not None and h is not None and (new.get("period") or 0) >= LAST_PERIOD[league]
                and abs(a - h) <= CLOSE_MARGIN[league]):
            closed.add(_key(new))
            out.append(Alert("CLOSE GAME", GOLD, new))
    if old["state"] == "in" and new["state"] == "post":
        mine, theirs = _int(new.get(f"{fav}_score")), _int(new.get(f"{'home' if fav == 'away' else 'away'}_score"))
        won = mine is not None and theirs is not None and mine > theirs
        out.append(Alert("WIN!" if won else "FINAL", WIN_GREEN if won else style.WHITE, new))
    return out


def frames(alert):
    """Two screens to alternate: the event (star + word) and the score."""
    if alert.lines:
        return tuple(render.centered(segs) for segs in alert.lines)
    word = render.centered([(ICON_CHAR["star"], None), ("  " + alert.word, alert.color)])
    g = alert.game
    if g.get("tennis") or g["state"] == "pre":
        segs = [(score_line(g), style.WHITE)]
    else:
        a, h = style.team_colors(g)
        segs = [(g["away"], a), (f" {g['away_score']}", style.WHITE), ("-", style.GRAY),
                (f"{g['home_score']} ", style.WHITE), (g["home"], h)]
        if len(render.strip(segs)) > render.W:            # long abbreviations: just the score
            segs = [(f"{g['away_score']}-{g['home_score']}", style.WHITE)]
    return word, render.centered(segs)


def sample():
    """A made-up alert for the 'Test alert' button."""
    g = {"league": "NFL", "id": "test", "away": "CHI", "home": "GB", "away_name": "Chicago Bears",
         "home_name": "Green Bay Packers", "away_score": "14", "home_score": "10", "state": "in",
         "period": 2, "detail": "5:31 - 2nd", "away_colors": ["0b162a", "c83803"],
         "home_colors": ["204e32", "ffb612"]}
    return Alert("TOUCHDOWN", style.team_colors(g)[0], g)


class Watcher(threading.Thread):
    """Polls favorite-team games and calls on_alert(Alert) for each big moment."""

    def __init__(self, settings, on_alert, stop_event, games_source=None, log=print, interval=POLL_S):
        super().__init__(daemon=True)
        self.s, self.on_alert, self.stop = settings, on_alert, stop_event
        self.games_source = games_source or scores.games
        self.log, self.interval = log, interval
        self.prev, self.closed = {}, set()

    def poll(self):
        terms = favorites.parse(self.s.favorites)
        if not self.s.alerts or not terms:
            return
        for league in [lg for lg in self.s.leagues if lg in scores.ALL]:
            try:
                games = self.games_source(league)
            except Exception:
                continue          # network hiccup; try again next poll
            for g in games:
                g.setdefault("league", league)
                if not favorites.side(g, terms):
                    continue
                k = _key(g)
                for a in diff(self.prev.get(k), g, terms, self.closed):
                    self.on_alert(a)
                self.prev[k] = dict(g)

    def run(self):
        while not self.stop.is_set():
            self.poll()
            end = time.time() + self.interval
            while time.time() < end and not self.stop.is_set():
                time.sleep(0.5)
