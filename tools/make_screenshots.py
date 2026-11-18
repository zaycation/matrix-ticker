"""Render the README images (LED-style PNGs and the scrolling GIF) from sample data.

    pip install Pillow
    python tools/make_screenshots.py      # writes docs/images/*
"""
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PIL import Image, ImageDraw  # noqa: E402

from matrix import font, render, screens, style, system, weather  # noqa: E402
from matrix.ticker import league_strip  # noqa: E402

OUT = os.path.join(ROOT, "docs", "images")
S, PAD = 9, 14                      # pixels per LED, border
BG, OFF = (12, 12, 14), (30, 31, 36)


def led_image(buf, width=90, scale=S):
    img = Image.new("RGB", (width * scale + 2 * PAD, 10 * scale + 2 * PAD), BG)
    d = ImageDraw.Draw(img)
    for y in range(10):
        for x in range(width):
            i = (y * width + x) * 3
            c = tuple(buf[i:i + 3])
            x0, y0 = PAD + x * scale, PAD + y * scale
            d.ellipse([x0, y0, x0 + scale - 2, y0 + scale - 2], fill=c if c != (0, 0, 0) else OFF)
    return img


def strip_image(cols, scale=6):
    """A whole scrolling line at once (what passes across the panel), with a little lead-in."""
    cols = [[(0, 0, 0)] * 10] * 3 + cols + [[(0, 0, 0)] * 10] * 2
    buf = bytes(c for y in range(10) for col in cols for c in col[y])
    return led_image(buf, len(cols), scale)


def save_strip(name, cols, max_cols=None):
    """max_cols keeps very long lines readable when GitHub shrinks the image."""
    if max_cols and len(cols) > max_cols:
        cols = cols[:max_cols]
    strip_image(cols).save(os.path.join(OUT, name))
    print("wrote", name)


def save(name, buf):
    led_image(buf).save(os.path.join(OUT, name))
    print("wrote", name)


GAMES = [
    {"away": "LAL", "home": "GSW", "away_score": "99", "home_score": "87", "state": "in",
     "detail": "2:31 - 4th", "away_colors": ["552583", "fdb927"], "home_colors": ["1d428a", "ffc72c"]},
    {"away": "NY", "home": "TOR", "away_score": "112", "home_score": "108", "state": "post",
     "detail": "Final/OT", "away_colors": ["006bb6", "f58426"], "home_colors": ["ce1141", "000000"]},
    {"away": "BOS", "home": "MIA", "away_score": "", "home_score": "", "state": "pre",
     "detail": "7:30 PM", "away_colors": ["007a33", "ba9653"], "home_colors": ["98002e", "f9a01b"]},
]


def fake_weather(url, params):
    if "geocoding" in url:
        return {"results": [{"name": "Los Angeles", "latitude": 34.05, "longitude": -118.24}]}
    hours = [f"2026-11-17T{h:02d}:00" for h in range(24)] + [f"2026-11-18T{h:02d}:00" for h in range(24)]
    return {
        "current": {"time": "2026-11-17T17:15", "temperature_2m": 66, "weather_code": 2, "is_day": 1},
        "daily": {"time": ["2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21"],
                  "weather_code": [2, 0, 61, 95, 3], "temperature_2m_max": [72, 75, 64, 61, 67],
                  "precipitation_probability_max": [0, 0, 70, 85, 15],
                  "sunrise": [f"2026-11-{d}T06:3{i}" for i, d in enumerate(range(17, 22))],
                  "sunset": [f"2026-11-{d}T16:4{7 - i}" for i, d in enumerate(range(17, 22))]},
        "hourly": {"time": hours, "temperature_2m": [58 + (h % 24) // 3 for h in range(48)],
                   "weather_code": [0] * 19 + [3] * 2 + [61] * 27,
                   "precipitation_probability": [0] * 21 + [40] * 27,
                   "is_day": [1 if 7 <= h % 24 < 17 else 0 for h in range(48)]},
    }


def main():
    os.makedirs(OUT, exist_ok=True)

    # scrolling ticker GIF
    cols = league_strip("NBA", GAMES, 5)
    frames = [led_image(render.frame(cols, off)) for off in range(-90, len(cols) + 1, 2)]
    frames[0].save(os.path.join(OUT, "ticker.gif"), save_all=True, append_images=frames[1:],
                   duration=55, loop=0, optimize=True)
    print("wrote ticker.gif")
    save_strip("ticker-line.png", cols)

    weather._get = fake_weather
    days = weather.segments("Los Angeles", "F", "daily")
    cut = next(k for k, (t, _) in enumerate(days) if t.strip() == "TODAY") - 1   # the gap before TODAY
    save_strip("weather-now.png", render.strip(days[:cut]))
    save_strip("weather-days.png", render.strip(days[cut + 1:]))
    weather._wx_cache.clear()
    hours = weather.segments("Los Angeles", "F", "hourly")
    cut = next(k for k, (t, _) in enumerate(hours) if t.strip() == "6PM") - 1
    save_strip("weather-hours.png", render.strip(hours[cut + 1:]))

    system.cpu_load, system.gpu_temp = (lambda: 42), (lambda: 58)
    save("dashboard.png", screens.dashboard(dt.datetime(2026, 11, 17, 17, 31)))
    save("calendar.png", screens.calendar(dt.date(2026, 11, 17)))
    save("counter.png", screens.counter("Chests", 37, flash=True))
    np = [(font.ICON_CHAR["note"], None), ("  MIDNIGHT DRIVE", style.WHITE), ("  -  ", style.GRAY),
          ("THE NIGHT OWLS", screens.CYAN)]
    save_strip("now-playing.png", render.strip(np))


if __name__ == "__main__":
    main()
