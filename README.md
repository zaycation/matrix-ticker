# Matrix Ticker

Turn the 900-LED Matrix display on the **Phanteks Evolv X2 Matrix** case into a full-color
live ticker: sports scores and the weather, scrolling across your case.

- **Scores:** NFL, NBA, MLB, WNBA, women's college basketball (top 25), and tennis Grand Slams.
  Team colors, live clock, red finals. Only games happening today are shown.
- **Weather:** current conditions, sunrise and sunset, plus the next 5 days or the next 5 hours.
- **Runs quietly in the system tray** and can start with Windows.

> Matrix Ticker talks to the display directly over USB. Phanteks NexLinq can't run at the same
> time, so the app closes it when the ticker starts (and can reopen it for you).

## Install

1. Download **MatrixTicker-Setup.exe** from the
   [latest release](https://github.com/zaycation/matrix-ticker/releases/latest).
2. Run it. If Windows shows **"Windows protected your PC"**, click **More info → Run anyway**
   (the app isn't code-signed yet).
3. Click through the installer. Leave **Start Matrix Ticker when Windows starts** checked if you
   want it running after every boot.

No admin rights or Python needed.

## Use

Open **Matrix Ticker** from the Start menu or desktop.

1. Tick what to show: the sports you follow and **WEATHER**.
2. For weather, type your city or ZIP code (e.g. `91367` or `Paris, FR`) and pick **5 days** or **5 hours**.
3. Press **▶ Run**. Press **■ Stop** to stop; your NexLinq layout comes back once NexLinq is reopened
   (**Launch NexLinq** button).

| Setting | What it does |
|---|---|
| Speed | How fast the ticker scrolls (pixels per second) |
| Padding | Space between games |
| Brightness | How bright the ticker is |
| Loop | Keep cycling (off = one pass, then stop) |
| Close NexLinq on Run | Closes NexLinq automatically when you press Run |
| Start the ticker when the app opens | With "start with Windows", the ticker runs right after boot |
| Reset defaults | Puts the settings back (keeps your weather location) |

**Closing the window** keeps Matrix Ticker running in the **system tray** (by the clock).
Right-click the tray icon to open it, run or stop the ticker, launch NexLinq, or quit.
The icon shows a green dot while the ticker is running.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Error: open failed` | The display isn't connected or is in use. Check its USB cable, and make sure NexLinq is closed (**Quit NexLinq**). |
| `Image upload failed ... Is NexLinq still running?` | NexLinq is open and fighting the ticker. Click **Quit NexLinq**, then Run. |
| `Couldn't close NexLinq` | NexLinq runs as Administrator. Close it from its own tray icon, or run Matrix Ticker as Administrator. |
| Weather: `couldn't find '...'` | Try a different spelling, a ZIP code, or add the country: `Springfield, US`. |
| Nothing shows / no games | Only games happening today are shown. Tick more sports or WEATHER. |
| "Matrix Ticker is already running" | It's in the system tray. Click the up-arrow by the clock to find it. |

## Uninstall

Windows **Settings → Apps → Installed apps → Matrix Ticker → Uninstall**.
Your settings are in `%APPDATA%\MatrixTicker` if you want to remove them too.

## Credits

Scores from ESPN. Weather data by [Open-Meteo.com](https://open-meteo.com) (free for non-commercial use).
Not affiliated with Phanteks.

For running from source, command-line options, and how the display's USB protocol was worked out,
see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) and [docs/PROTOCOL.md](docs/PROTOCOL.md).
