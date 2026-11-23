"""Scores ticker for the Matrix900, run league by league like a TV ticker.

For each league: fetch fresh scores -> pack games into <=50-char pages
("NBA:" only on the first) -> show each page until it has fully scrolled
-> buffer -> next league.

    python main.py --calibrate          # once: time the scroll speed, saved to calib.json
    python main.py --preview --demo     # see the pages in the terminal, no panel/network
    python main.py                      # run (quiet); -v prints each page
    python main.py --leagues NFL,NBA --page-buffer 1 --league-gap 4
    python main.py --nba --once -v      # debug: one sport, one pass, then exit
    python main.py --nfl --speed-scale 1.1 --once -v   # try a scale without editing config.json
    python main.py --style scroll       # full-color scrolling ticker (close NexLinq first)
    python main.py --style scroll --speed 11 --brightness 60
    python gui.py                       # the control window

Speed scale: 1.0 = the tuned baseline. Each 0.1 adds/removes 0.1 of scroll time
per page (1.1 = a bit longer, 0.9 = a bit shorter). Per-sport values and the
extra for live games live in config.json:
    {"scale": {"default": 1.0, "NFL": 0.9, "NBA": 1.0}, "live_bonus": 0.0}

Only live games and games starting today (Pacific time) are shown, so
off-season leagues are skipped automatically. Everything is white by default;
--colors groups games by color instead: live (green), final (gray), upcoming (white).
"""
import argparse
import json
import os
import sys
import time

from matrix import render, scores
from matrix.ticker import CALENDAR, COUNTER, DASHBOARD, FANTASY, MEETINGS, NOWPLAYING, WEATHER, ScrollTicker, Settings

TEXT_MAX = 50
LIVE, FINAL, UPCOMING, INFO = (0, 255, 80), (170, 170, 170), (255, 255, 255), (80, 160, 255)
from matrix.paths import CALIB_FILE, CONFIG_FILE, RESTORE_FILE
DEFAULT_CONFIG = {"scale": {"default": 1.0}, "live_bonus": 0.0}
BASE_SCALE = 4.4   # tuned on the panel: scale 1.0 means 4.4x the calibrated scroll time
CAL_LONG = "1" + "." * 49      # 50 characters, a single "1" so "when it comes back" is unambiguous
VISIBLE_CHARS = 15            # ~90 px wide panel / ~6 px per character

# Characters the panel can't draw show up as "A" (tested with tools/paneltest.py chars).
# Works: letters, digits, space : - @ / . , # + ( ) ! ? ' % * = < >
# Fails: | & _ ; $ " ~
REPLACE = {"|": "-", "&": "", "_": "-", ";": ",", "$": "", '"': "'", "~": "-"}  # "TA&M" -> "TAM"

DEMO = {
    "NFL": [
        {"away": "PIT", "home": "CIN", "away_score": "3", "home_score": "31", "state": "in", "detail": "15:00 - 4th"},
        {"away": "NE", "home": "DET", "away_score": "10", "home_score": "35", "state": "post", "detail": "Final"},
        {"away": "KC", "home": "ATL", "away_score": "35", "home_score": "13", "state": "post", "detail": "Final"},
        {"away": "SF", "home": "SEA", "away_score": "", "home_score": "", "state": "pre", "detail": "5:20 PM"},
    ],
    "NBA": [
        {"away": "LAL", "home": "GSW", "away_score": "99", "home_score": "87", "state": "in", "detail": "2:31 - 4th"},
        {"away": "NYK", "home": "TOR", "away_score": "85", "home_score": "43", "state": "post", "detail": "Final"},
    ],
}


# ---------- formatting ----------

def short_detail(g):
    d = g["detail"].upper()
    if g["state"] == "post":
        return "F" if d == "FINAL" else d.replace("FINAL", "F")        # "F", "F/OT"
    if g["state"] == "in" and " - " in d:
        clock, period = d.split(" - ", 1)                               # "15:00 - 4TH"
        return f"{period} {clock}"                                       # -> "4TH 15:00"
    return d                                                             # upcoming: "5:20 PM"


def game_text(g):
    if g.get("tennis"):
        tail = g["detail"] if g["state"] == "pre" else g["sets"] + (" F" if g["state"] == "post" else "")
        return f"{g['away']} V {g['home']} {tail}"
    if g["state"] == "pre":
        return f"{g['away']} @ {g['home']} {short_detail(g)}"
    return f"{g['away']} @ {g['home']} {g['away_score']}-{g['home_score']} {short_detail(g)}"


def clean(text):
    text = text.upper()
    for bad, good in REPLACE.items():
        text = text.replace(bad, good)
    return text


def pages_for(league, games, sep, league_sep):
    """Pack games into <=50-char pages, grouped by state so each page has one color."""
    pages, first = [], True
    for state, color in (("in", LIVE), ("post", FINAL), ("pre", UPCOMING)):
        page = ""
        for g in (x for x in games if x["state"] == state):
            item = clean(game_text(g))
            if first:
                item, first = f"{league}{league_sep}{item}", False
            candidate = f"{page}{sep}{item}" if page else item
            if len(candidate) <= TEXT_MAX:
                page = candidate
            else:
                if page:
                    pages.append((page, color, state))
                page = item[:TEXT_MAX]
        if page:
            pages.append((page, color, state))
    return pages


# ---------- scroll timing ----------

def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_FILE) as f:
            user = json.load(f)
        cfg["scale"].update(user.get("scale", {}))
        cfg["live_bonus"] = user.get("live_bonus", cfg["live_bonus"])
    except (OSError, ValueError):
        pass
    return cfg


def load_calib():
    try:
        with open(CALIB_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def scroll_seconds(text, cal, scale=1.0):
    """Constant scroll speed: a pass covers the text plus the panel's width,
    scaled from the measured 50-character pass."""
    if not cal:
        return 15.0
    per_char = cal["long_s"] / (cal["long_len"] + VISIBLE_CHARS)
    return (len(text) + VISIBLE_CHARS) * per_char * scale


def calibrate(panel):
    print("Calibration: a '1' followed by 49 dots is timed twice. Each time, press Enter\n"
          "the moment the '1' appears on the right, then again when the '1' appears on the\n"
          "right a second time (one full pass).\n")
    runs = []
    for n in (1, 2):
        panel.show_text(CAL_LONG, color=UPCOMING)
        input(f"[run {n}] Press Enter when the '1' appears on the right...")
        t0 = time.perf_counter()
        input("        ...Enter again when the '1' appears on the right again.")
        runs.append(time.perf_counter() - t0)
        print(f"        {runs[-1]:.2f} s\n")
    if max(runs) > 1.25 * min(runs):
        print(f"The two runs differ a lot ({runs[0]:.2f} vs {runs[1]:.2f} s). Consider running again.")
    result = {"long_len": len(CAL_LONG), "long_s": round(sum(runs) / len(runs), 2)}
    with open(CALIB_FILE, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Saved to {CALIB_FILE}. Just run: python main.py")


TEAM_COLORS_DEMO = {
    "LAL": ["552583", "fdb927"], "GSW": ["1d428a", "ffc72c"], "NYK": ["006bb6", "f58426"],
    "TOR": ["ce1141", "000000"], "PIT": ["000000", "ffb612"], "CIN": ["fb4f14", "000000"],
    "NE": ["002244", "c60c30"], "DET": ["0076b6", "b0b7bc"], "KC": ["e31837", "ffb81c"],
    "ATL": ["a71930", "000000"], "SF": ["aa0000", "b3995d"], "SEA": ["002244", "69be28"],
}
for _games in DEMO.values():
    for _g in _games:
        _g["away_colors"] = TEAM_COLORS_DEMO.get(_g["away"], [])
        _g["home_colors"] = TEAM_COLORS_DEMO.get(_g["home"], [])


def run_scroll(panel, args, leagues):
    settings = Settings(speed=args.speed, step=args.step, brightness=args.brightness,
                        padding=len(args.sep), leagues=leagues, loop=not args.once,
                        location=args.location, units="C" if args.celsius else "F",
                        weather_mode="hourly" if args.hourly else "daily", weather_count=args.count,
                        screen_seconds=args.screen_seconds, clock_24h=args.h24,
                        cpu_meter=args.cpu_meter, gpu_meter=args.gpu_meter,
                        keep_awake=not args.allow_sleep, calendar_url=args.ical, favorites=args.favorites, sleeper_user=args.sleeper, sleeper_league=args.sleeper_league, favorites_only=args.only_favorites, alerts=not args.no_alerts,
                        verbose=args.verbose, league_gap=args.league_gap)
    source = (lambda lg: DEMO.get(lg, [])) if args.demo else None
    from matrix.counter import Counter
    counter = Counter()
    from matrix.timer import Timer
    timer = Timer()
    if args.timer:
        timer.start(minutes=args.timer)
    timer.listen()
    if panel:
        if settings.keep_awake:
            from matrix import power
            power.keep_awake(True)
        print("Scroll ticker running (NexLinq must be closed). Ctrl+C to stop.")
        ScrollTicker(panel, settings, games_source=source, counter=counter, timer=timer).run()
    else:
        print("\x1b[2J", end="")

        def log_below(msg):   # messages go on a line under the preview
            print(f"\x1b[{render.preview_rows() + 2};1H\x1b[K{msg}", flush=True)
        ScrollTicker(None, settings, log=log_below, games_source=source, show=render.preview,
                     counter=counter, timer=timer).run()


def restore(panel):
    """Put the saved NexLinq layout back (see tools/save_layout.py)."""
    try:
        with open(RESTORE_FILE) as f:
            pkts = [bytes.fromhex(h) for h in json.load(f)["packets"]]
    except (OSError, ValueError, KeyError):
        print("No layouts/default.json: panel keeps the last page. See tools/save_layout.py.")
        return
    print("Restoring NexLinq layout..." + (" done." if panel.replay(pkts) else " no echo, check the panel."))


# ---------- main loop ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="print instead of sending")
    ap.add_argument("--demo", action="store_true", help="sample data, no network")
    ap.add_argument("--calibrate", action="store_true", help="measure scroll times (saved to calib.json)")
    ap.add_argument("--leagues", default=",".join(scores.ALL), help="any of: " + ",".join(scores.ALL))
    ap.add_argument("--page-buffer", type=float, default=1.0, help="extra seconds after every page")
    ap.add_argument("--league-gap", type=float, default=3.0, help="extra seconds after each league's last page")
    ap.add_argument("--sep", default="     ", help="text between games (default: 5 spaces)")
    ap.add_argument("--league-sep", default=" : ", help="text after the league name")
    ap.add_argument("-v", "--verbose", action="store_true", help="print each page as it's sent")
    ap.add_argument("--colors", action="store_true", help="color pages by status instead of all white")
    ap.add_argument("--speed-scale", type=float, default=None,
                    help="override every sport's scale (1.0 = baseline, 1.1 = a bit longer)")
    ap.add_argument("--once", action="store_true", help="one pass through the leagues, then exit")
    ap.add_argument("--no-restore", action="store_true", help="don't restore layouts/default.json on exit")
    ap.add_argument("--style", choices=["text", "scroll"], default="text",
                    help="text = text widget (default); scroll = full-color images (close NexLinq)")
    ap.add_argument("--speed", type=float, default=Settings.speed, help="scroll style: pixels per second")
    ap.add_argument("--step", type=int, default=Settings.step, help="scroll style: pixels moved per frame")
    ap.add_argument("--brightness", type=int, default=100, help="scroll style: 10-100 percent")
    for lg in scores.ALL:
        ap.add_argument(f"--{lg.lower()}", dest="only", action="append_const", const=lg,
                        help=f"show only {lg} (combine flags for several)")
    ap.add_argument("--weather", dest="only", action="append_const", const=WEATHER,
                    help="include the weather forecast (scroll style; needs --location)")
    for flag, item in (("--dashboard", DASHBOARD), ("--calendar", CALENDAR), ("--counter", COUNTER),
                       ("--nowplaying", NOWPLAYING), ("--fantasy", FANTASY), ("--meetings", MEETINGS)):
        ap.add_argument(flag, dest="only", action="append_const", const=item,
                        help=f"include the {item.lower()} screen (scroll style)")
    ap.add_argument("--ical", default="", metavar="URL", help="private iCal link for --meetings")
    ap.add_argument("--allow-sleep", action="store_true", help="let Windows go to sleep while running")
    ap.add_argument("--timer", type=float, default=0, metavar="MINUTES",
                    help="start a countdown that takes over the panel (scroll style)")
    ap.add_argument("--screen-seconds", type=float, default=10.0, help="seconds per static screen")
    ap.add_argument("--24h", dest="h24", action="store_true", help="24-hour clock on the dashboard")
    ap.add_argument("--location", default="", help='weather location: city, ZIP, "91367, US" or "lat,lon"')
    ap.add_argument("--celsius", action="store_true", help="weather in Celsius")
    ap.add_argument("--hourly", action="store_true", help="weather: hours ahead instead of days ahead")
    ap.add_argument("--sleeper", default="", help="Sleeper username for --fantasy")
    ap.add_argument("--sleeper-league", default="", help="only Sleeper leagues whose name contains this")
    ap.add_argument("--favorites", default="", help='favorite teams, e.g. "Bears, Sparks" (listed first, starred)')
    ap.add_argument("--only-favorites", action="store_true", help="show only games with a favorite team")
    ap.add_argument("--no-alerts", action="store_true", help="no big-moment alerts for favorite teams")
    ap.add_argument("--cpu-meter", default=Settings.cpu_meter, choices=["load", "ram"],
                    help="dashboard top meter")
    ap.add_argument("--gpu-meter", default=Settings.gpu_meter, choices=["temp", "load", "vram", "power", "fan"],
                    help="dashboard bottom meter (NVIDIA)")
    ap.add_argument("--count", type=int, default=Settings.weather_count, help="weather: how many days/hours (default 5)")
    args = ap.parse_args()

    panel = None
    if not args.preview:
        from matrix.transport import Matrix
        panel = Matrix()

    try:
        if args.calibrate:
            if not panel:
                sys.exit("--calibrate needs the panel (drop --preview)")
            calibrate(panel)
            return

        cal, cfg = load_calib(), load_config()
        leagues = args.only or args.leagues.split(",")
        if panel and not cal:
            print("No calib.json yet: using 15 s per page. Run --calibrate for accurate timing.")
        if panel and not args.verbose:
            print("Ticker running. Ctrl+C to stop. (-v to see each page)")
        if args.style == "scroll":
            run_scroll(panel, args, leagues)
            return

        while True:
            for league in leagues:
                if league in (WEATHER, NOWPLAYING, DASHBOARD, CALENDAR, COUNTER, FANTASY, MEETINGS):
                    continue               # these need the full-color scroll style
                try:
                    games = DEMO.get(league, []) if args.demo else scores.games(league)
                except Exception as e:  # network hiccup: skip this league this cycle
                    print(f"{league}: {e}", file=sys.stderr)
                    continue
                pages = pages_for(league, games, args.sep, args.league_sep)
                if not args.colors:
                    pages = [(t, UPCOMING, st) for t, _, st in pages]
                scale = args.speed_scale if args.speed_scale is not None else \
                    cfg["scale"].get(league, cfg["scale"]["default"])
                for i, (text, color, state) in enumerate(pages):
                    last = i == len(pages) - 1
                    user_s = scale + (cfg["live_bonus"] if state == "in" else 0.0)
                    s = BASE_SCALE + (user_s - 1.0)            # 1.0 -> 4.4, 1.1 -> 4.5
                    wait = scroll_seconds(text, cal, s) + args.page_buffer + (args.league_gap if last else 0)
                    if panel:
                        ok = panel.show_text(text, color=color)
                        if args.verbose or not ok:
                            print(f"{'sent  ' if ok else 'NO ACK'} {wait:5.1f}s scale {user_s:.2f} {text}", flush=True)
                        time.sleep(wait)
                    else:
                        r, g, b = color
                        print(f"\x1b[38;2;{r};{g};{b}m{text}\x1b[0m  ({len(text)} chars, {wait:.1f}s)")
                        time.sleep(0.3)
                if pages and not panel:
                    print()
            if args.once:
                break
    finally:
        if panel:
            if not args.no_restore and not args.calibrate:
                restore(panel)
            panel.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\x1b[0m")
