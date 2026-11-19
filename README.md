# 🎬 Cinema WatchDog

Watches **Scene Cinemas – Cairo Festival City** and **VOX Cinemas – City Centre Almaza** for you and
emails you the moment seats that match what you want become available.

It's a small web app that runs on your own Windows PC (no hosting, no accounts, nothing to pay for).
Open it in your browser, set up monitors, and leave it running.

## What it can watch

| | Scene CFC | VOX Almaza |
|---|---|---|
| Pick a movie | ✅ | ✅ |
| Dates / show times (empty = all) | ✅ | ✅ |
| Experience / hall | ScreenX · Premiere · Standard | Standard · GOLD (premium recliners) · MAX (Infinity Vision) |
| Number of seats, side by side, optional split into groups | ✅ | ✅ |
| Specific rows or seats (click them on a seat map) | ✅ | ✅ |
| Seat type | from the hall (e.g. ScreenX) | **Regular** (normal) · **Premium** |
| Alert when a sold-out show becomes bookable | ✅ | ✅ |

**VOX seat maps** are read through VOX's guest booking flow (nothing is reserved, and the booking session is
abandoned right after reading). That flow was down for hours on 2026-11-19. If it breaks again, the app notices
that *every* seat map is failing and falls back to emailing you when a sold-out showtime becomes bookable,
marked "seat map couldn't be read".

For Avengers: Doomsday, VOX lists two movies: **AVENGERS: DOOMSDAY** (Standard + GOLD at Almaza) and
**AVENGERS: DOOMSDAY (INFINITY VISION)** (MAX + Standard). Create a monitor for each one you care about.
Scene lists one movie that has ScreenX, Premiere and Standard showtimes.

Monitors can be changed later with **Edit**. Saving re-checks straight away with the new settings.

## Setup (5 minutes, once)

1. **Python 3.10+** must be installed (it is on this PC: 3.12).
2. Double-click **`start.bat`**. The first run installs packages, then your browser opens
   <http://localhost:5000>. Keep the black window open.
3. **Email alerts.** Gmail needs an *App Password* (your normal password won't work):
   - Turn on 2-Step Verification for the Gmail account that will **send** alerts.
   - Go to <https://myaccount.google.com/apppasswords>, create one (name it "Cinema WatchDog"), and copy the 16 characters.
   - In the app, click **⚙ Settings**, enter that Gmail address and the app password, add the recipient
     addresses (comma-separated), then **Send test email**.
4. Create monitors: pick a cinema, then the movie, then filters → **Start monitoring**.

### Keep it running

- Monitoring only happens while the app is running and the PC is awake. Set Windows
  *Settings → System → Power → Screen and sleep → "When plugged in, put my device to sleep after" = Never*.
- Optional: run it automatically in the background at every login:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1
  ```
  (Undo with `Unregister-ScheduledTask -TaskName "CinemaWatchDog" -Confirm:$false`.)
- You can open the page from your phone on the same Wi-Fi by starting it with `set CWD_HOST=0.0.0.0`
  before `start.bat` and browsing to `http://<your-PC-IP>:5000`. Anyone on that network can then use it,
  so only do this on your home Wi-Fi.

## How alerts work

- Every ~2 minutes (configurable in Settings, ±15% random jitter) each active monitor is checked.
- You get **one email per change**: when a showtime starts matching, you're emailed. If those seats get
  taken and later free up again, you're emailed again. You won't get the same alert every 2 minutes.
- When you create a monitor, the first check runs straight away. If seats are already available, you're
  emailed right away.
- If the email fails (wrong app password, no internet), it retries on the next check.
- The page also shows matches live, beeps, and shows a browser notification if the tab is open.
- Scene's "Hold" seats (in someone's basket) count as taken. They often free up after ~10 minutes, and
  you'll get an alert then.

### Matching rules

- **Seats needed + "next to each other"** means N free seats in a row with no gap or aisle between them.
- **Rows** (e.g. `E, F, G`): only seats in those rows count.
- **Specific seats** (e.g. `F10, F11, F12`): only those seats count. With "next to each other" on, N of them must be adjacent.
- **Split into up to N groups of at least M seats**: used only when no single unbroken block fits your whole party.
- **Seat type** (VOX): Regular and/or Premium.
- Rows and seats can be combined. Leave both empty to accept any seat.

## Files

```
app.py                       web server + API (Flask/waitress, port 5000)
cinemawatchdog/scene.py      Scene CFC scraper (showtimes + seat-plan JSON)
cinemawatchdog/vox.py        VOX Egypt scraper: showtimes + seat maps (curl_cffi Chrome impersonation for Akamai)
cinemawatchdog/monitor.py    background checker, matching and alert logic
cinemawatchdog/notifier.py   Gmail/SMTP emails
static/index.html            the UI
data/                        your monitors, settings (incl. app password), alert history, log
```

Your app password is stored in `data/settings.json` on this PC only. To avoid saving it to disk, set the
`CWD_SMTP_USER` / `CWD_SMTP_PASSWORD` environment variables instead.

## If something breaks

The cinemas can change their websites at any time. If a monitor shows a red **error** badge, check the
**Activity log** tab. Usually the site changed its layout and the scraper in `cinemawatchdog/` needs a small update.
