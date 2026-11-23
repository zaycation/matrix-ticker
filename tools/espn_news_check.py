"""Peek at ESPN's fantasy player-news feed, to see if it can replace Sleeper-style blurbs.

    python tools/espn_news_check.py
"""
import gzip
import json
import urllib.request

URLS = [
    "https://site.api.espn.com/apis/fantasy/v2/games/ffl/news/players?limit=5",
    "https://site.api.espn.com/apis/fantasy/v2/games/ffl/news/players?playerId=3139477&limit=3",  # Mahomes
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "matrix-ticker", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw)


for url in URLS:
    print("=" * 70)
    print(url)
    try:
        d = get(url)
    except Exception as e:
        print("  failed:", e)
        continue
    print("  top-level keys:", list(d)[:12])
    items = d.get("feed") or d.get("articles") or d.get("news") or []
    print("  items:", len(items), "| resultsCount:", d.get("resultsCount"))
    for a in items[:5]:
        who = ", ".join(c.get("description", "") for c in a.get("categories") or [] if c.get("type") == "athlete")
        text = (a.get("story") or a.get("description") or "").replace("\n", " ")
        print(f"  - {a.get('published', '?')[:16]} | {who or '?'} | {a.get('headline', '')}")
        print(f"      {text[:160]}")
