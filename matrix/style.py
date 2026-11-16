"""Color rules for the full-color (image) ticker styles.

- League name: red while any game isn't final, green when all are final,
  white when none have started.
- ":" "@" "-" and the live game clock/period: gray.
- "F", "F/OT": red.
- Team abbreviations: the team's own color (made bright enough for LEDs; if both
  teams look alike, the home team uses its alternate color).
- Everything else: white.
"""

WHITE, GRAY, RED, GREEN = (255, 255, 255), (110, 110, 110), (255, 30, 30), (0, 220, 80)


def _rgb(hexstr):
    try:
        h = hexstr.strip().lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else None
    except (AttributeError, ValueError):
        return None


def _visible(rgb):
    """Scale dark colors up so they show on LEDs; near-black becomes None."""
    if rgb is None:
        return None
    m = max(rgb)
    if m < 40:
        return None
    if m < 200:
        k = 200 / m
        rgb = tuple(min(255, int(c * k)) for c in rgb)
    return rgb


def _distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def team_colors(g):
    """(away_rgb, home_rgb), visible and distinct where possible."""
    def options(key):
        opts = [_visible(_rgb(h)) for h in g.get(key) or []]
        return [o for o in opts if o] or [WHITE]
    away, home = options("away_colors"), options("home_colors")
    a, h = away[0], home[0]
    if _distance(a, h) < 120:
        for alt in home[1:] + away[1:]:
            if _distance(a, alt) >= 120:
                if alt in home:
                    h = alt
                else:
                    a = alt
                break
    return a, h


def league_color(games):
    states = {g["state"] for g in games}
    if states == {"pre"}:
        return WHITE
    if states == {"post"}:
        return GREEN
    return RED


def status_segments(g, short_detail):
    d = short_detail(g)
    if g["state"] == "post":
        return [(d, RED)]
    if g["state"] == "in":
        return [(d, GRAY)]
    return [(d, WHITE)]          # upcoming start time


def game_segments(g, short_detail):
    """One game as colored segments: LAL @ GSW 99-87 4TH 2:31"""
    if g.get("tennis"):
        tail = g["detail"] if g["state"] == "pre" else g["sets"]
        segs = [(g["away"], WHITE), (" V ", GRAY), (g["home"], WHITE), (" " + tail, WHITE)]
        if g["state"] == "post":
            segs.append((" F", RED))
        return segs
    a, h = team_colors(g)
    segs = [(g["away"], a), (" @ ", GRAY), (g["home"], h), (" ", WHITE)]
    if g["state"] != "pre":
        segs += [(str(g["away_score"]), WHITE), ("-", GRAY), (str(g["home_score"]), WHITE), (" ", WHITE)]
    return segs + status_segments(g, short_detail)


def league_segments(league, games):
    return [(league, league_color(games)), (" : ", GRAY)]
