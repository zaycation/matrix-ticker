"""Scores from ESPN's public (unofficial, undocumented) scoreboard JSON.

Only "happening" games are returned: live now, or starting today in Pacific
time. Off-season leagues therefore return nothing and get skipped.
"""
import datetime as dt
import json
import urllib.request

try:
    from zoneinfo import ZoneInfo
    PT = ZoneInfo("America/Los_Angeles")
except Exception as e:  # Windows has no built-in time zone data
    raise SystemExit("Time zone data missing. Run:  pip install tzdata") from e

URL = "https://site.api.espn.com/apis/site/v2/sports/{}/scoreboard"

TEAM_LEAGUES = {
    "NFL": "football/nfl",
    "NBA": "basketball/nba",
    "MLB": "baseball/mlb",
    "WNBA": "basketball/wnba",
    "NCAAW": "basketball/womens-college-basketball",  # top-25 games only
}
TENNIS_TOURS = {"ATP": "tennis/atp", "WTA": "tennis/wta"}  # Grand Slams only
GRAND_SLAMS = ("australian open", "french open", "roland garros", "wimbledon", "us open")
ALL = list(TEAM_LEAGUES) + list(TENNIS_TOURS)


def fetch(path):
    req = urllib.request.Request(URL.format(path), headers={"User-Agent": "matrix-ticker"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def start_pt(iso):
    """ESPN dates look like 2026-11-16T01:20Z."""
    if not iso:
        return None
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(PT)


def clock_pt(t):
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def happening(state, start):
    return state == "in" or (start is not None and start.date() == dt.datetime.now(PT).date())


def rank(c):
    return (c.get("curatedRank") or {}).get("current", 99)


def team_games(league):
    """Yield dicts: away, home, away_score, home_score, state (pre/in/post), detail."""
    for ev in fetch(TEAM_LEAGUES[league]).get("events", []):
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        st = ev["status"]["type"]
        start = start_pt(ev.get("date"))
        if not happening(st["state"], start):
            continue
        if league == "NCAAW" and min(rank(teams["away"]), rank(teams["home"])) > 25:
            continue
        yield {
            "away": teams["away"]["team"]["abbreviation"],
            "home": teams["home"]["team"]["abbreviation"],
            # team colors as hex strings like "552583"; may be missing
            "away_colors": [teams["away"]["team"].get("color"), teams["away"]["team"].get("alternateColor")],
            "home_colors": [teams["home"]["team"].get("color"), teams["home"]["team"].get("alternateColor")],
            "away_score": teams["away"].get("score", ""),
            "home_score": teams["home"].get("score", ""),
            "state": st["state"],
            # upcoming games get our own Pacific time instead of ESPN's text
            "detail": clock_pt(start) if st["state"] == "pre" and start else st["shortDetail"],
        }


def _player(c):
    a = c.get("athlete") or {}
    name = a.get("shortName") or a.get("displayName") or "?"
    return name.split()[-1].upper()  # last name


def tennis_matches(tour):
    """Grand Slam singles matches, same dict shape as team_games (player = 'team').
    Untested against live data: no Grand Slam runs until the Australian Open in January."""
    for ev in fetch(TENNIS_TOURS[tour]).get("events", []):
        if not any(s in ev.get("name", "").lower() for s in GRAND_SLAMS):
            continue
        for grp in ev.get("groupings", []):
            label = ((grp.get("grouping") or {}).get("displayName") or "").lower()
            if label and "singles" not in label:
                continue
            for m in grp.get("competitions", []):
                st = ((m.get("status") or {}).get("type") or {})
                state, start = st.get("state", "pre"), start_pt(m.get("date"))
                if not happening(state, start) or len(m.get("competitors", [])) != 2:
                    continue
                p1, p2 = m["competitors"]
                sets = " ".join(f"{int(a['value'])}-{int(b['value'])}"
                                for a, b in zip(p1.get("linescores", []), p2.get("linescores", [])))
                yield {
                    "away": _player(p1), "home": _player(p2), "away_score": "", "home_score": "",
                    "state": state, "tennis": True, "sets": sets,
                    "detail": clock_pt(start) if state == "pre" and start else "",
                }


def games(league):
    return list(tennis_matches(league) if league in TENNIS_TOURS else team_games(league))
