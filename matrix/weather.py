"""Weather from Open-Meteo (free, no API key, non-commercial use; credit: Open-Meteo.com).

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
LABEL, HIGH, LOW, RAIN = (80, 200, 255), (255, 150, 40), (90, 170, 255), (60, 140, 255)

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
        "current": "temperature_2m,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "temperature_unit": "fahrenheit" if units == "F" else "celsius",
        "timezone": "auto", "forecast_days": 5,
    })
    _wx_cache[key] = (time.time(), data)
    return name, data


def _icon(code):
    return WMO.get(int(code), ("", "cloud"))[1] if code is not None else "cloud"


def segments(location, units="F"):
    """Colored segments for the scroll ticker: NOW + today + next 4 days."""
    name, d = forecast(location, units)
    cur, daily = d.get("current", {}), d.get("daily", {})
    segs = [(name.upper(), LABEL), (" : ", style.GRAY), ("NOW ", style.GRAY),
            (font.ICON_CHAR[_icon(cur.get("weather_code"))], None),
            (f" {round(cur.get('temperature_2m', 0))}°", style.WHITE)]
    days = daily.get("time", [])
    for i, day in enumerate(days[:5]):
        label = "TODAY" if i == 0 else dt.date.fromisoformat(day).strftime("%a").upper()
        hi, lo = daily["temperature_2m_max"][i], daily["temperature_2m_min"][i]
        rain = (daily.get("precipitation_probability_max") or [None] * 5)[i]
        segs += [("     ", style.WHITE), (label + " ", style.GRAY), (font.ICON_CHAR[_icon(daily["weather_code"][i])], None),
                 (f" {round(hi)}°", HIGH), (f" {round(lo)}°", LOW)]
        if rain is not None and rain >= 20:
            segs.append((f" {round(rain)}%", RAIN))
    return segs
