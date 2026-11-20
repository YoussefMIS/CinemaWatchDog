# Cinema WatchDog

**Get an email the moment the cinema seats you want become available.**

Cinema WatchDog watches sold-out or nearly full showtimes at
**Scene Cinemas – Cairo Festival City** and **VOX Cinemas – City Centre Almaza** (Egypt). It checks the
live seat maps every couple of minutes. When seats that match your criteria free up, it emails you the
cinema, date, time and seats, with a direct booking link.

It's a small web app that runs on your own computer. You don't need an account, hosting or a subscription,
and your data never leaves your machine.

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![License: MIT](https://img.shields.io/badge/license-MIT-green) ![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

---

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Using the app](#using-the-app)
- [How alerts work](#how-alerts-work)
- [Running in the background](#running-in-the-background)
- [Troubleshooting](#troubleshooting)
- [Privacy and security](#privacy-and-security)
- [Project structure](#project-structure)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## Features

| | Scene CFC | VOX Almaza |
|---|:---:|:---:|
| Choose a movie and dates (leave empty for all) | ✅ | ✅ |
| Watch a **time window** (e.g. 7 PM – 11 PM), including showtimes added later | ✅ | ✅ |
| Filter by experience / hall | ScreenX · Premiere · Standard | Standard · GOLD · MAX (Infinity Vision) |
| Number of seats, side by side | ✅ | ✅ |
| Split a large group across several blocks | ✅ | ✅ |
| Pick specific rows or seats on an interactive seat map | ✅ | ✅ |
| Seat type | from the hall | **Regular** · **Premium** |

- **Email alerts** to as many recipients as you like, with a **Book** link for each match.
- **Live dashboard** showing what is available right now. It also plays a sound and shows a browser
  notification while the page is open.
- **Edit, pause or delete** monitors at any time. **Check now** runs a check immediately.
- **Activity log and alert history**, so you can see what the app is doing.
- **Read-only.** The app never reserves, holds or buys seats. It only reads the seat map, then releases
  the booking session straight away.

## Requirements

- **Python 3.10 or newer**: <https://www.python.org/downloads/>
  On Windows, tick **"Add python.exe to PATH"** during installation.
- An **email account to send alerts from**. A Gmail account with an
  [App Password](https://support.google.com/accounts/answer/185833) is recommended.
- A computer that stays **on and awake** while you want monitoring to run.

## Installation

### 1. Download

Clone the repository:

```bash
git clone https://github.com/YoussefMIS/CinemaWatchDog.git
cd CinemaWatchDog
```

Or click **Code → Download ZIP** on GitHub and unzip it anywhere.

### 2. Start the app

**Windows:** double-click **`start.bat`**.

The first run creates a private Python environment (`.venv`) and installs the dependencies, which takes a
minute or two. Then your browser opens at <http://localhost:5000>. Keep the black console window open.
Closing it stops monitoring.

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py --open
```

On later runs you only need `source .venv/bin/activate` and `python app.py --open`.

### 3. Set up email alerts

Choose **one** of these two options.

**Option A: in the app (simplest).** Click **⚙ Settings**, then enter:

- the sender Gmail address,
- its app password,
- the recipient addresses.

Then click **Send test email**.

**Option B: in a `.env` file.** This keeps the password out of the app's data files.

```bash
copy .env.example .env      # Windows
cp .env.example .env        # macOS / Linux
```

Open `.env` in a text editor, fill in `CWD_SMTP_USER`, `CWD_SMTP_PASSWORD` and `CWD_RECIPIENTS`, then
restart the app. Use **Send test email** in Settings to confirm it works.

> **Creating a Gmail App Password:** turn on
> [2-Step Verification](https://myaccount.google.com/signinoptions/two-step-verification) for the sending
> account. Then open <https://myaccount.google.com/apppasswords>, create a password named
> "Cinema WatchDog" and copy the 16 characters. Your normal Gmail password will **not** work.

## Configuration

Everything can be configured from the **⚙ Settings** page. You can also use environment variables or a
`.env` file in the project folder; see [`.env.example`](.env.example) for a commented template.

| Variable | Default | Description |
|---|---|---|
| `CWD_SMTP_USER` | none | Email address that sends the alerts. Overrides Settings. |
| `CWD_SMTP_PASSWORD` | none | App password for that account. Overrides Settings, and is never written to disk. |
| `CWD_SMTP_HOST` | `smtp.gmail.com` | Mail server. |
| `CWD_SMTP_PORT` | `465` | `465` uses SSL; any other port (e.g. `587`) uses STARTTLS. |
| `CWD_RECIPIENTS` | none | Comma-separated recipients. A starting value that Settings can change. |
| `CWD_INTERVAL_SECONDS` | `120` | Time between checks (minimum 30). A starting value that Settings can change. |
| `CWD_HOST` | `127.0.0.1` | `0.0.0.0` lets other devices on your network open the app. |
| `CWD_PORT` | `5000` | Web server port. |
| `CWD_DATA_DIR` | `./data` | Where monitors, settings and alert history are stored. |

Real environment variables take priority over values in `.env`.

## Using the app

1. **Pick a cinema**, then a **movie**. Avengers titles are listed first.
2. Optionally narrow it down by **date** and **experience** (e.g. ScreenX, MAX). Anything you leave
   empty means "all".
3. Choose which **show times** to watch:
   - **Any time:** every showtime.
   - **Time window:** every showtime that starts between two times, e.g. 7:00 PM – 11:00 PM. This
     includes showtimes the cinema adds later, so it's the best choice for popular releases. Leave one
     side empty for "from …" or "until …". Windows can cross midnight (e.g. 9:00 PM – 1:00 AM).
   - **Exact times:** only the specific showtimes you pick.
4. Set the **number of seats** and whether they must be **next to each other**.
5. Optionally restrict it to **rows** or **specific seats**. Type them in (e.g. `E, F, G` or `F10, F11`)
   or click them on the seat map. For VOX, you can also choose **Regular** and/or **Premium** seats.
6. Click **Start monitoring**. The first check runs straight away.

### Matching rules

| Setting | Meaning |
|---|---|
| **Time window** | The showtime's start time is inside the window (both ends included). After-midnight shows count as part of the previous night. |
| **Seats needed + next to each other** | N free seats in one row with no gap or aisle between them. |
| **Split into up to N groups of at least M seats** | Used only when no single block fits the whole party, e.g. 16 seats as 8 + 8. |
| **Rows** | Only seats in these rows count. |
| **Specific seats** | Only these seats count. |
| **Seat type** (VOX) | Regular, Premium, or both. |

Rows and specific seats can be combined. Leave both empty to accept any seat in the hall.

> **VOX tip:** VOX lists *Avengers: Doomsday* and *Avengers: Doomsday (Infinity Vision)* as two separate
> movies. Create a monitor for each one you want to watch.

## How alerts work

- Every active monitor is checked about every 2 minutes. Each interval gets a small random variation, so
  requests don't look automated.
- You get **one email per change**. When a showtime starts matching, you're emailed. If the seats are
  taken and later free up again, you're emailed again. You won't get the same alert on every check.
- If sending fails (e.g. wrong password or no internet), the alert is retried on the next check.
- Seats in someone else's basket ("Hold") count as taken. They are often released after about 10 minutes,
  and you'll be alerted then.
- **Alerts are only sent for real seats.** You're never emailed just because a showtime became bookable.
  If a cinema's booking system is down and its seat maps can't be read, the monitor shows a yellow
  **seat maps unavailable** badge and keeps checking. You're emailed only once matching seats can be
  confirmed.

## Running in the background

Monitoring only runs while the app is running and the computer is awake.

- **Prevent sleep (Windows):** *Settings → System → Power → Screen and sleep*, then set
  *"When plugged in, put my device to sleep after"* to **Never**.
- **Start automatically at login (Windows):** run `start.bat` once, then in PowerShell from the project
  folder:

  ```powershell
  powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1
  ```

  The app then runs silently in the background at <http://localhost:5000>. To remove it:

  ```powershell
  Unregister-ScheduledTask -TaskName "CinemaWatchDog" -Confirm:$false
  ```

- **Open it from your phone:** set `CWD_HOST=0.0.0.0` in `.env`, restart the app, and browse to
  `http://<your-computer's-IP>:5000` from a device on the same Wi-Fi. The app has no login, so do this
  **only on a trusted home network**.

## Troubleshooting

| Problem | What to do |
|---|---|
| `python` is not recognized | Reinstall Python and tick **Add python.exe to PATH**, or use the `py` launcher. |
| Test email fails with "Username and Password not accepted" | Use a Gmail **App Password**, not your normal password, and make sure 2-Step Verification is on. |
| A monitor shows a red **error** badge | Open the **Activity log** tab. A cinema has probably changed its website, and the scraper in `cinemawatchdog/` needs an update. Please open an issue. |
| A monitor shows **seat maps unavailable** | The cinema's online booking is temporarily down, so seats can't be checked. No alerts are sent meanwhile, and the app recovers automatically once booking is back. |
| Port 5000 is already in use | Set `CWD_PORT=5050` (or any free port) in `.env`. |
| No alerts arrive | Check that the monitor is not paused, check your spam folder, and look at the **Alerts** tab. |

## Privacy and security

- All data (monitors, settings, alert history and logs) is stored locally in the `data/` folder. Nothing
  is sent anywhere except requests to the two cinema websites and your mail server.
- If you save the app password in **Settings**, it's stored in plain text in `data/settings.json` on your
  computer. To avoid that, put it in `.env` or an environment variable instead.
- `data/` and `.env` are excluded from Git by `.gitignore`. Never commit or share them.
- By default the app only accepts connections from your own computer (`127.0.0.1`).

## Project structure

```
app.py                        Web server and REST API (Flask + Waitress)
cinemawatchdog/
  scene.py                    Scene CFC: showtimes and seat plans
  vox.py                      VOX Egypt: showtimes and seat maps (browser-like TLS via curl_cffi)
  monitor.py                  Background checker, seat matching and alert logic
  notifier.py                 Email alerts (SMTP)
  store.py                    JSON storage for monitors, settings and alert history
  providers.py                Registry of supported cinemas
  common.py                   Shared data types and helpers
static/index.html             The web interface
start.bat                     Windows launcher (sets up .venv on first run)
install-autostart.ps1         Optional: start automatically at Windows login
.env.example                  Configuration template
LICENSE                       MIT license
```

## Disclaimer

Cinema WatchDog is an independent personal project. It is **not affiliated with, endorsed by or connected
to** Scene Cinemas, VOX Cinemas or Majid Al Futtaim. It reads the same public pages a visitor sees in a web
browser and never makes bookings. Please use it responsibly: keep the check interval reasonable and don't
run many copies at once. The cinemas can change their websites at any time, which may break monitoring
until the app is updated.

## License

Released under the [MIT License](LICENSE). You're free to use, modify and share it.
