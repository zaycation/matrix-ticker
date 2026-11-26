"""Check the patch-notes sources from this PC (what the ticker would show right now).

    python tools/patchnotes_check.py                       # the games saved in the app
    python tools/patchnotes_check.py "GTA 6" ""            # one game, watching the news
    python tools/patchnotes_check.py "WoW Forever" https://news.blizzard.com/en-us/article/24315281
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from matrix import patches  # noqa: E402
from matrix.paths import CONFIG_FILE  # noqa: E402


def games():
    if len(sys.argv) >= 3:
        return [{"name": sys.argv[1], "url": sys.argv[2]}]
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f).get("gui", {}).get("patch_games") or patches.DEFAULT_GAMES
    except (OSError, ValueError):
        return patches.DEFAULT_GAMES


for g in games():
    name, url = g.get("name", ""), g.get("url", "")
    print("=" * 70)
    print(f"{name}: {url or '(no page: watching news headlines)'}")
    try:
        if url:
            page = patches.fetch(url)
            secs = patches.sections(page)
            print(f"  page: {len(page):,} characters, {len(secs)} dated sections:",
                  ", ".join(str(d) for d, _, _ in secs[:6]))
            if not secs:
                print("  No dated sections found. If the page shows notes in a browser, send me this output.")
                continue
            upd = patches.page_update(url, lambda u: page)
            print(f"  newest: {upd['date']}  {upd['changes']} changes")
            for cat, change in upd["picks"]:
                print(f"    {cat}: {change}")
        else:
            heads = patches.news_updates(name)
            print(f"  {len(heads)} 'patch notes' headlines in the last 3 days")
            for _id, when, title in heads[:5]:
                print(f"    {when or '?'}  {title}")
        print("  on the panel:", "".join(t for t, _ in patches.segments(
            name, upd if url else {"headline": heads[0][2]} if heads else {"headline": "(nothing yet)"})))
    except Exception as e:
        print("  failed:", e)
