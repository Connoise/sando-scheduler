# Sando Scheduler

A self-hosted household scheduler for a single Tailnet. It has two runtime
components that share a plain-file data layer on the host machine (a Lenovo
ThinkCentre), plus a separate AI host agent ("Hermes") that edits the same
files from chat:

1. **Reminder daemon** (`reminder_daemon.py`) — a Python service that watches
   `reminders.json` and sends Telegram messages at scheduled times. Purely a
   timer and message sender; no AI in this path.
2. **Web app** (`sando_web/`) — a FastAPI + PWA mobile calendar served over
   Tailscale for viewing and editing the schedule from a phone.

Everything is reasoned about in **Hawaii time (HST)**. There is no database:
the master schedule lives in monthly `.xlsx` workbooks, operational reminder
state in `reminders.json`, an audit trail in `changelog.csv`, and defaults in
`config.json` — all under `SCHEDULE_DIR` (default `/home/Schedule`).

## Status

The web app is feature-complete through the phased plan in
[`mobile_app_plan.md`](./mobile_app_plan.md):

| Phase | Feature | State |
|---|---|---|
| v0.1 | Read-only weekly grid over Tailscale | ✅ |
| v0.2 | Monthly view + day tap-through | ✅ |
| v0.3 | Add-event form, conflict warning, dual-write | ✅ |
| v0.4 | Event-detail sheet with Cancel / Delete | ✅ |
| v0.5 | PWA polish (manifest, service worker, offline shell) | ✅ |

The reminder daemon is in production on the host. Test suite: **81 tests
passing** (`python -m pytest tests/`).

## Components

### Reminder daemon (`reminder_daemon.py`)

- Polls `reminders.json` every 60s.
- Sends a Telegram message when `remind_at <= now`, `sent == false`, and
  `status == "active"`; marks the entry `sent: true` after delivery.
- Coalesces all reminders due in the same poll cycle into one message.
- Skips `cancelled` / `deleted` entries but keeps them as history.
- Sends a **Sunday-morning weekly digest** (8:00 AM HST) of the week's active
  events; tracked in a small state file so it fires once per week.
- Prunes sent and cancelled/deleted entries older than 7 days from
  `reminders.json` (permanent history stays in `changelog.csv`).
- File-locked (`fcntl.flock`) reads/writes so it never races the host agent
  or the web app.

### Web app (`sando_web/`)

A thin, server-rendered client over the same files the host agent manages —
it does **not** call any AI. Served over Tailscale, installable as a PWA.

Routes:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Redirect to the current week (HST) |
| `GET` | `/week/{YYYY-MM-DD}` | Weekly grid (7 days × 48 half-hour slots) |
| `GET` | `/month` · `/month/{YYYY-MM}` | Monthly grid with per-day event previews |
| `GET` | `/event/new` | Add-event form |
| `POST` | `/event` | Create event (dual-write) |
| `GET` | `/event/{date}/{name}` | Event detail sheet |
| `POST` | `/event/{date}/{name}/{cancel\|delete}` | Cancel or delete an event |
| `GET` | `/api/events?from=…&to=…` | JSON feed for a date range |
| `GET` | `/manifest.webmanifest` · `/sw.js` | PWA manifest + service worker |
| `GET` | `/healthz` | Liveness probe |

Behavior highlights:

- **Reads** parse the weekly `.xlsx` sheets (the human-editable source of
  truth) and cache them in-process, keyed by workbook mtime.
- **Writes** are dual-writes: the event is written into the correct
  spreadsheet cell(s), reminder entries are appended to `reminders.json`, and
  an `ADD` row is logged to `changelog.csv`. Cancel/Delete annotate the cell
  (`Name (cancelled)` / `(deleted)`), flip the reminder `status`, and log a
  `CANCEL`/`DELETE` row.
- Default reminders ("Day of" + "1 hour before") and event duration (60 min)
  come from `config.json`, matching `scheduler_instructions.md`.
- Cancelled/deleted events render struck-through rather than hidden, so
  history stays visible. A "now" line marks the current slot in week view.
- The service worker caches the app shell and last-viewed pages for an offline
  read; non-GET requests bypass the cache.

#### Module map

| File | Responsibility |
|---|---|
| `app.py` | FastAPI app factory, routes, form parsing/validation |
| `config.py` | `Settings`, HST timezone, `config.json` defaults |
| `calendar_utils.py` | Pure helpers: week boundaries, slot labels, workbook/sheet routing |
| `schedule_io.py` | Read side — parse weekly sheets, mtime cache, build week/month/detail views |
| `schedule_write.py` | Write side — events, reminders, changelog, cancel/delete, file locking |

## Shared data layer

All paths are under `SCHEDULE_DIR`:

```
/home/Schedule/
├── <YYYY>/<YYYY>_<Month>.xlsx   ← master schedule (one sheet per week, 30-min slots)
├── reminders.json               ← operational reminder state (daemon's source of truth)
├── changelog.csv                ← append-only audit log (ADD / CANCEL / DELETE)
└── config.json                  ← defaults (duration, reminder offsets, morning time…)
```

All three writers — the host agent, the daemon, and the web app — coordinate
through the same locking convention: `fcntl.flock` on `reminders.json` and
`changelog.csv`, and a sibling `.lock` file for each workbook (openpyxl is not
safe for concurrent writes).

## Repository structure

```
sando-scheduler/
├── README.md
├── reminder_daemon_spec.md       ← daemon spec (schema, systemd, skeleton)
├── scheduler_instructions.md     ← operating rules for the host agent (Hermes)
├── mobile_app_plan.md            ← web app design + phased plan
├── reminder_daemon.py            ← the daemon
├── reminder-daemon.service       ← systemd unit (daemon)
├── sando-web.service             ← systemd unit (web app, binds to Tailscale)
├── deploy.sh                     ← installs the daemon on the host
├── requirements.txt
├── sando_web/
│   ├── app.py
│   ├── config.py
│   ├── calendar_utils.py
│   ├── schedule_io.py
│   ├── schedule_write.py
│   ├── static/                   ← app.css, icon.svg, manifest.webmanifest, sw.js
│   └── templates/                ← base, week, month, event_form, event_detail
└── tests/                        ← 81 tests (pytest)
```

## Running locally

### Web app

```bash
pip install -r requirements.txt
SCHEDULE_DIR=/home/Schedule \
    python -m uvicorn sando_web.app:app --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`. Point `SCHEDULE_DIR` at a directory containing
the workbook layout above (or an empty dir — the add-event flow bootstraps
workbooks and sheets on first write).

### Tests

```bash
pip install -r requirements.txt pytest httpx   # httpx backs the FastAPI test client
python -m pytest tests/
```

### Daemon

See [`reminder_daemon_spec.md`](./reminder_daemon_spec.md) for full details.
TL;DR:

1. Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `REMINDERS_FILE`.
2. `pip install requests`
3. `python reminder_daemon.py` (or deploy as a systemd service).

## Deployment

Both components run as systemd services on the host.

- **Daemon:** `./deploy.sh` copies `reminder_daemon.py` into `SCHEDULE_DIR`,
  installs dependencies, provisions the secrets file (see below), and enables
  `reminder-daemon.service`.
- **Web app:** install `sando-web.service` and bind it to the host's Tailscale
  interface — set `SANDO_WEB_HOST` to the Tailnet IP so the port is never
  reachable on the LAN. The phone joins the same Tailnet and hits
  `http://<tailnet-host>:8765/`; access control is Tailscale device identity,
  no extra auth layer. See `mobile_app_plan.md` §Access Model.

## Secrets

The bot token and chat ID are **not** stored in the repo. In production they
live in `/etc/sando-scheduler/reminder-daemon.env` (root-owned, `chmod 600`),
which `reminder-daemon.service` loads via `EnvironmentFile=`. Create it from
[`reminder-daemon.env.example`](./reminder-daemon.env.example) — `deploy.sh`
does this for you and refuses to start the service while the placeholders are
unfilled. Any `*.env` file is gitignored as a safety net.

> **Rotate on exposure.** A bot token previously committed to this repo is
> still recoverable from git history, so it must be revoked and reissued via
> @BotFather. Removing it from the working tree is not enough on its own.

## Environment variables

**Daemon** (`reminder_daemon.py`) — `TELEGRAM_*` come from the secrets file above:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token for the Telegram bot (from @BotFather) |
| `TELEGRAM_CHAT_ID` | Target Scheduling chat ID |
| `REMINDERS_FILE` | Path to `reminders.json` (default `/home/Schedule/reminders.json`) |
| `DAEMON_STATE_FILE` | Weekly-digest bookkeeping (default `/home/Schedule/reminder_daemon_state.json`) |

**Web app** (`sando_web/`):

| Variable | Description |
|---|---|
| `SCHEDULE_DIR` | Root of the data layer (default `/home/Schedule`); `changelog.csv` and `config.json` are derived from it |
| `REMINDERS_FILE` | Override the reminders path (default `<SCHEDULE_DIR>/reminders.json`) |
| `SANDO_WEB_HOST` / `SANDO_WEB_PORT` | Bind address/port, consumed by `sando-web.service` (defaults `127.0.0.1` / `8765`) |

## Docs

- [`reminder_daemon_spec.md`](./reminder_daemon_spec.md) — daemon logic, schema, systemd setup, script skeleton.
- [`scheduler_instructions.md`](./scheduler_instructions.md) — operating rules for the host agent (Hermes): file layout, defaults, cancel/delete semantics, reminder rules.
- [`mobile_app_plan.md`](./mobile_app_plan.md) — web app design, routes, concurrency model, and the phased build plan.
