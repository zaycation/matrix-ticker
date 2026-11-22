"""Favorite teams: typed as a comma-separated list, e.g. "Bears, Sparks, Dodgers".

A term matches a team if it equals the team's abbreviation (CHI) or is a whole word or
phrase in its full name ("Bears" in "Chicago Bears"). "Chicago" would match every
Chicago team. Tennis players match by name too.
"""
import re


def parse(text):
    return [t.strip().lower() for t in re.split(r"[,;]", text or "") if t.strip()]


def matches(terms, abbr, name):
    abbr, name = (abbr or "").lower(), (name or "").lower()
    for t in terms:
        if t == abbr or re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", name):
            return True
    return False


def side(g, terms):
    """'away', 'home' or None: which team in game g is a favorite (away wins a tie)."""
    if not terms:
        return None
    if matches(terms, g.get("away"), g.get("away_name")):
        return "away"
    if matches(terms, g.get("home"), g.get("home_name")):
        return "home"
    return None
