"""Update check: is there a newer release on GitHub than this copy?

One small request to GitHub's public API (no login), at startup and once a day.
Only the installed app checks; running from source you update with git pull.
"""
import json
import re
import urllib.request

from .version import __version__

REPO = "zaycation/matrix-ticker"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"


def parse(v):
    """'v0.1.10' -> (0, 1, 10); None if it isn't a version."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def newer(latest, current=__version__):
    a, b = parse(latest), parse(current)
    return a is not None and b is not None and a > b


def check(current=__version__):
    """(version, url) of a newer release, or None (also None when running from source or offline)."""
    if parse(current) is None:
        return None
    try:
        req = urllib.request.Request(LATEST, headers={"User-Agent": "matrix-ticker",
                                                      "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            rel = json.load(r)
    except Exception:
        return None
    tag = rel.get("tag_name", "")
    if rel.get("draft") or rel.get("prerelease") or not newer(tag, current):
        return None
    return tag.lstrip("v"), rel.get("html_url") or RELEASES_PAGE
