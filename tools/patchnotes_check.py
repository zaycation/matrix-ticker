"""Check the patch-notes sources from this PC (what the ticker would show right now).

    python tools/patchnotes_check.py                       # the games saved in the app
    python tools/patchnotes_check.py --all                 # also every change, shortened
    python tools/patchnotes_check.py "WoW Forever" https://news.blizzard.com/en-us/article/24315281
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from matrix import patches  # noqa: E402
from matrix.paths import CONFIG_FILE  # noqa: E402


def games():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) >= 2:
        return [{"name": args[0], "url": args[1]}]
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f).get("gui", {}).get("patch_games") or patches.DEFAULT_GAMES
    except (OSError, ValueError):
        return patches.DEFAULT_GAMES


for g in games():
    name, url = g.get("name", ""), g.get("url", "")
    if not name:
        continue
    print("=" * 70)
    print(f"{name}: {url or '(no page link set: not watched)'}")
    if not url:
        continue
    try:
        page = patches.fetch(url)
        secs = patches.sections(page)
        print(f"  page: {len(page):,} characters, {len(secs)} dated sections:",
              ", ".join(str(d) for d, _, _ in secs[:6]))
        if not secs:
            print("  No dated sections found. If the page shows notes in a browser, send me this output.")
            continue
        upd = patches.page_update(url, lambda u: page)
        print("  on the panel:", "".join(t for t, _ in patches.segments(name, upd)))
        if "--all" in sys.argv:
            n, every = patches.summarize(secs[0], top=10 ** 6)
            print(f"  every change in the newest section, shortened ({n}):")
            for cat, change in every:
                print(f"    {cat + ': ' if cat else ''}{change}")
    except Exception as e:
        print("  failed:", e)
