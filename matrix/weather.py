"""Weather from Open-Meteo (free, no API key, non-commercial use; credit: Open-Meteo.com).

Two views: "daily" = now + today and the following days (highs only);
"hourly" = now + the next few hours (how many is a setting; 5 by default). Both also show the next sunrise and sunset.
Everything comes from one cached request.

Location can be a city ("Woodland Hills"), a postal code ("91367"), either with a
country/state after a comma ("91367, US"), or "lat,lon". It's looked up once and cached.
Forecasts refresh at most every 15 minutes.
"""
import datetime as dt
import json
import time
import urllib.parse
import urllib.request

from . import font, style

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REFRESH_S = 15 * 60

# icon keys are drawn by font.ICONS
WMO = {
    0: ("CLEAR", "sun"), 1: ("MOSTLY CLEAR", "sun"), 2: ("PARTLY CLOUDY", "partly"), 3: ("CLOUDY", "cloud"),
    45: ("FOG", "fog"), 48: ("FOG", "fog"),
    51: ("DRIZZLE", "rain"), 53: ("DRIZZLE", "rain"), 55: ("DRIZZLE", "rain"),
    56: ("ICY DRIZZLE", "snow"), 57: ("ICY DRIZZLE", "snow"),
    61: ("RAIN", "rain"), 63: ("RAIN", "rain"), 65: ("HEAVY RAIN", "rain"),
    66: ("ICY RAIN", "snow"), 67: ("ICY RAIN", "snow"),
    71: ("SNOW", "snow"), 73: ("SNOW", "snow"), 75: ("HEAVY SNOW", "snow"), 77: ("SNOW", "snow"),
    80: ("SHOWERS", "rain"), 81: ("SHOWERS", "rain"), 82: ("HEAVY SHOWERS", "rain"),
    85: ("SNOW SHOWERS", "snow"), 86: ("SNOW SHOWERS", "snow"),
    95: ("STORMS", "storm"), 96: ("STORMS", "storm"), 99: ("STORMS", "storm"),
}
LABEL, HIGH, RAIN = (80, 200, 255), (255, 150, 40), (60, 140, 255)

_geo_cache, _wx_cache = {}, {}


def _get(url, params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "matrix-ticker"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def locate(location):
    """-> (lat, lon, display_name). Raises ValueError if nothing matches."""
    loc = (location or "").strip()
    if not loc:
        raise ValueError("no weather location set")
    if loc in _geo_cache:
        return _geo_cache[loc]
    parts = [p.strip() for p in loc.split(",")]
    try:
        lat, lon = float(parts[0]), float(parts[1])
        result = (lat, lon, f"{lat:.2f},{lon:.2f}")
    except (ValueError, IndexError):
        params = {"name": parts[0], "count": 10, "format": "json"}
        hits = _get(GEOCODE_URL, params).get("results") or []
        if len(parts) > 1:  # narrow by country code / name / state, e.g. "91367, US" or "Paris, TX"
            want = parts[1].lower()
            narrowed = [h for h in hits if want in (str(h.get("country_code", "")).lower(),
                        str(h.get("country", "")).lower(), str(h.get("admin1", "")).lower())]
            hits = narrowed or hits
        if not hits:
            raise ValueError(f"couldn't find '{loc}'")
        h = hits[0]
        result = (h["latitude"], h["longitude"], h.get("name", loc))
    _geo_cache[loc] = result
    return result


def forecast(location, units="F"):
    lat, lon, name = locate(location)
    key = (round(lat, 3), round(lon, 3), units)
    cached = _wx_cache.get(key)
    if cached and time.time() - cached[0] < REFRESH_S:
        return name, cached[1]
    data = _get(FORECAST_URL, {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,weather_code,is_day",
        "daily": "weather_code,temperature_2m_max,precipitation_probability_max,sunrise,sunset",
        "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
        "temperature_unit": "fahrenheit" if units == "F" else "celsius",
        "timezone": "auto", "forecast_days": 16,
    })
    _wx_cache[key] = (time.time(), data)
    return name, data


def _icon(code, is_day=1):
    name = WMO.get(int(code), ("", "cloud"))[1] if code is not None else "cloud"
    if not is_day:                     # no sun at night
        name = {"sun": "moon", "partly": "moonpartly"}.get(name, name)
    return name


def _hour_label(iso):
    h = int(iso[11:13])
    return f"{h % 12 or 12}{'AM' if h < 12 else 'PM'}"


def _clock(iso):
    h, m = int(iso[11:13]), iso[14:16]
    return f"{h % 12 or 12}:{m}{'AM' if h < 12 else 'PM'}"


def _sun_segments(d, gap):
    """Next sunrise and next sunset (whichever comes first leads), local time."""
    now = (d.get("current", {}).get("time") or "")[:16]
    daily = d.get("daily", {})
    events = []
    for key in ("sunrise", "sunset"):
        upcoming = [t for t in daily.get(key) or [] if t and t[:16] > now]
        if upcoming:
            events.append((upcoming[0], key))
    segs = []
    for t, key in sorted(events):
        segs += [gap, (font.ICON_CHAR[key], None), (" " + _clock(t), style.WHITE)]
    return segs


def _rain(segs, pct):
    if pct is not None and pct >= 20:
        segs.append((f" {round(pct)}%", RAIN))


def segments(location, units="F", mode="daily", count=5):
    """Colored segments for the scroll ticker.
    daily: NOW + today and the following days (count in all).  hourly: NOW + the next count hours."""
    count = max(1, int(count))
    name, d = forecast(location, units)
    cur = d.get("current", {})
    segs = [(name.upper(), LABEL), (" : ", style.GRAY), ("NOW ", style.GRAY),
            (font.ICON_CHAR[_icon(cur.get("weather_code"), cur.get("is_day", 1))], None),
            (f" {round(cur.get('temperature_2m', 0))}°", style.WHITE)]
    gap = ("     ", style.WHITE)
    segs += _sun_segments(d, gap)
    if mode == "hourly":
        h = d.get("hourly", {})
        times = h.get("time", [])
        now_hour = (cur.get("time") or "")[:13]          # e.g. "2026-11-17T17"
        start = next((i for i, t in enumerate(times) if t[:13] == now_hour), 0)
        for i in range(start + 1, min(start + 1 + count, len(times))):
            segs += [gap, (_hour_label(times[i]) + " ", style.GRAY),
                     (font.ICON_CHAR[_icon(h["weather_code"][i], h.get("is_day", [1] * len(times))[i])], None),
                     (f" {round(h['temperature_2m'][i])}°", style.WHITE)]
            _rain(segs, (h.get("precipitation_probability") or [None] * len(times))[i])
        return segs
    daily = d.get("daily", {})
    rain = daily.get("precipitation_probability_max") or []
    for i, day in enumerate(daily.get("time", [])[:count]):
        label = "TODAY" if i == 0 else dt.date.fromisoformat(day).strftime("%a").upper()
        segs += [gap, (label + " ", style.GRAY), (font.ICON_CHAR[_icon(daily["weather_code"][i])], None),
                 (f" {round(daily['temperature_2m_max'][i])}°", HIGH)]
        _rain(segs, rain[i] if i < len(rain) else None)
    return segs
