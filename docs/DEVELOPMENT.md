# Development

## Run from source

```
pip install -r requirements.txt
pythonw gui.py            # the app (add --tray to start hidden in the tray)
```

From source, settings live in the project folder; the installed app uses `%APPDATA%\MatrixTicker`.

## Command line (`main.py`)

```
python main.py --style scroll --preview --demo --nba               # terminal preview, sample data
python main.py --style scroll --preview --weather --location 91367 # weather preview (add --hourly)
python main.py --style scroll --speed 24 --brightness 80           # full-color ticker on the panel
python main.py --nba --once -v                                     # one sport, one pass, verbose
python main.py                                                     # older single-color text style
```

Sport flags: `--nfl --nba --mlb --wnba --ncaaw --atp --wta --weather` (combine them).
Screens: `--dashboard --calendar --counter --nowplaying`, `--screen-seconds 10`, `--24h`.
Preview example: `python main.py --style scroll --preview --dashboard --calendar --counter`.
Scroll style: `--speed` (px/s), `--step`, `--brightness`, `--league-gap`, `--sep`.
Weather: `--location`, `--hourly`, `--count N`, `--celsius`.
Favorites/alerts: `--favorites "Bears, 76ers"`, `--only-favorites`, `--no-alerts`. Fantasy: `--fantasy --sleeper USER [--sleeper-league NAME]`. Timer: `--timer 25` (minutes). Meetings: `--meetings --ical URL`. `--allow-sleep` lets Windows sleep. Ctrl+C stops and restores `layouts/default.json`.

Text style only (the original single-color ticker using the panel's text widget):
`--calibrate`, `--speed-scale`, `--page-buffer`, `config.json` `scale` / `live_bonus`.

## Project layout

| Path | What |
|---|---|
| `gui.py` | Control window and tray icon |
| `main.py` | Command-line ticker |
| `matrix/transport.py` | USB/HID sender (text widget, bitmap frames, replays) |
| `matrix/ticker.py` | Scroll engine shared by the GUI and CLI |
| `matrix/render.py`, `font.py` | 90x10 frame rendering, pixel font and weather icons |
| `matrix/scores.py`, `style.py` | ESPN data and color rules |
| `matrix/weather.py` | Open-Meteo forecast |
| `matrix/screens.py`, `canvas.py` | Dashboard, calendar, counter screens; small/big fonts |
| `matrix/system.py`, `media.py`, `counter.py` | PC stats, now playing, hotkey counter |
| `matrix/nexlinq.py` | Find / quit / launch NexLinq |
| `tools/` | Reverse-engineering helpers (captures, panel tests); `make_screenshots.py` renders the README images |
| `packaging/` | Icon and Inno Setup installer script |

## Saving your NexLinq layout (optional)

So Stop / exit can put your NexLinq layout back without reopening NexLinq. Needs Wireshark + USBPcap.

```
tshark -i \\.\USBPcap3 -w loadout.pcapng -a duration:15   (click Sent! in NexLinq while it records)
python tools/save_layout.py loadout.pcapng default
```

## Building the installer

Publish a GitHub release with a tag like `v0.2.0`. GitHub Actions (`.github/workflows/build.yml`)
builds the app with PyInstaller, packs it with Inno Setup, and attaches
`MatrixTicker-Setup-0.2.0.exe` to the release. It can also be run by hand from the Actions tab
(the installer is then a downloadable artifact).
