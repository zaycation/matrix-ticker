# matrix-ticker

Live NFL/NBA/WNBA scores on the Phanteks Matrix-900 (Evolv X2 Matrix).

## Run

1. In NexLinq: full-width layout (one slot), Creator → Text widget, scrolling on, Sent.
2. `pip install hidapi tzdata` (tzdata gives Windows the Pacific time zone)
3. From the folder containing `main.py`:

```
python main.py --calibrate        # once: time two scroll lengths (saved to calib.json)
python tools/paneltest.py chars   # which punctuation the panel can draw
python tools/paneltest.py colors  # which colors look right
python main.py --preview --demo   # check output in the terminal, no panel, no network
python main.py --preview          # live scores, terminal only
python main.py                    # live scores on the panel
python main.py --leagues NFL,NBA --page-buffer 1 --league-gap 4
```

Live games are green, finals gray, upcoming white. Only live games and games starting
today (Pacific) are shown, so off-season leagues are skipped. Leagues: NFL, NBA, MLB,
WNBA, NCAAW (top 25), ATP, WTA (Grand Slams). Quiet by default; `-v` prints each page. Stop with Ctrl+C.

## Protocol (decoded from USB captures)

The panel is an HID device (VID 2E3C, PID 6500, vendor usage page 0xFF1B).
Every packet is 64 bytes: `[0]=01` report ID, `[1]=command`, `[5]=payload length`.
The panel echoes each packet back to every open handle. It draws widgets itself; NexLinq never sends pixels.

| Cmd | Bytes | Meaning |
|---|---|---|
| 06 | `01 06 00 00 00 3a` + unix time (big-endian, `[6..9]`) + sensor values | NexLinq's once-a-second live data |
| 04 | `01 04 00 00 00 01 b4` | Begin update (`b4`/`84` depends on layout) |
| 05 | `01 05 ff 00 00 01 00` | Prepare |
| 02 | `01 02 00 00 00 n+1 idx` + text, ff-padded to 50, 7 zeros | Text for widget `idx` |
| 03 | `01 03 count 00 index 29` + 41 bytes | One widget: layout, category, item, scroll, position, text/bg/icon RGB |

A text packet on its own is ignored. Always send the full sequence 04 → 05 → 02 → 03.

Creator Text widget, `03` payload: `layout 04 00 scroll 02 | text RGB | bg RGB | icon RGB`.

## Tools

- `tools/find_device.py`: list HID devices
- `tools/descriptor.py`: dump the panel's HID report descriptor
- `tools/analyze.py`: `summary` / `changes` / `diff` on tshark captures (`--addr 3.9.`, `--dir in`)
- `tools/send_full.py`: replay the old layout-05 sequence with custom text (kept for reference)

## Restore your NexLinq layout on exit

Record NexLinq sending your loadout once, then save it:

```
tshark -i \\.\USBPcap3 -w loadout.pcapng -a duration:15     (click Sent! in NexLinq while it records)
python tools/save_layout.py loadout.pcapng default
```

Ctrl+C (or the end of `--once`) then replays `layouts/default.json`. `--no-restore` skips it.

## Tuning

`config.json` holds per-sport scroll scales. 1.0 is the tuned baseline; each 0.1 adds or
removes a little time per page. `live_bonus` is added for in-progress games.

```json
{"scale": {"default": 1.0, "NFL": 0.9, "NBA": 1.0}, "live_bonus": 0.0}
```

Debug one sport: `python main.py --nba --once -v` (add `--speed-scale 1.1` to try a value).

## Roadmap

- Full color (team colors, gray separators, red F): investigate the Creator EDITOR widget,
  which likely sends pixel data. The text widget only supports one color per page.
- Cycle content: sports ticker, weather (National Weather Service API), maybe local concerts.
- Cycle through layouts saved in NexLinq (replay their captured upload sequences) between tickers.
- GUI for easy customization.
- Public release: GitHub repo, setup docs, share with other Matrix case owners.
