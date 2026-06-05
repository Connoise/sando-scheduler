# Mobile Calendar App — Design Plan

## Goal

A mobile-accessible app for viewing and adding events on the Sando scheduler. The host machine (Lenovo ThinkCentre, where `reminder_daemon.py` and the spreadsheet live) is reachable from a phone via Tailscale. The app reads/writes the same files the host agent (Hermes) already manages per `scheduler_instructions.md`:

- `/home/Schedule/<YYYY>/<YYYY_Month>.xlsx` — the master schedule
- `/home/Schedule/reminders.json` — reminders state (source of truth for the UI)
- `/home/Schedule/changelog.csv` — append-only audit log
- `/home/Schedule/config.json` — defaults

The app does **not** call any AI. It is a thin client over the same data layer the host agent uses.

## Access Model — Tailscale

- The host already runs `reminder-daemon.service`. Add a second service, `sando-web.service`, that serves an HTTP app bound to the host's Tailscale interface (`tailscale0`) on a fixed port (e.g., `:8765`).
- Phone joins the same Tailnet. The phone's browser (or a PWA install) hits `http://<tailnet-hostname>:8765/`.
- No public exposure, no auth layer beyond Tailscale's device identity. Tailscale ACL restricts the port to the user's own devices.
- TLS: optional. If desired, use Tailscale's MagicDNS + `tailscale cert` to terminate HTTPS at the app and enable PWA installability.

## Stack

Keep it boring and host-friendly:

- **Backend**: Python + FastAPI (already have `requests` and `python-telegram-bot` in the toolchain; FastAPI is a small add).
- **Spreadsheet I/O**: `openpyxl` (same library the host agent uses).
- **Frontend**: server-rendered HTML + a small amount of vanilla JS, packaged as a PWA (manifest + service worker for offline view of cached week). No SPA framework needed for this size.
- **Calendar UI**: hand-rolled grid views. The spreadsheet data is already in a week-per-sheet, 30-minute-slot shape — the week view maps 1:1.

## Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Redirects to current week view |
| `GET` | `/week/{YYYY-MM-DD}` | Weekly view (week containing the date) |
| `GET` | `/month` | Redirects to current month view |
| `GET` | `/month/{YYYY-MM}` | Monthly view |
| `GET` | `/event/new` | Add-event form |
| `POST` | `/event` | Create event |
| `GET` | `/api/events?from=...&to=...` | JSON feed of events in a date range (used by the frontend for partial refresh) |

## Views

### Weekly View

- Mirrors the spreadsheet's weekly sheet: 7 day columns × 48 half-hour rows, 12-hour labels.
- Touch-friendly: each filled cell is tappable for event details (event name, start/end, reminders, status).
- "Now" line drawn across the current half-hour row.
- Top bar: ◀ / ▶ to swap weeks, "Today" button, link to month view.
- Cancelled and deleted events render with a strikethrough and dimmed text; they are not hidden, so the user can still see history.

### Monthly View

- Standard 7×5 (or 7×6) grid.
- Each day cell shows the count of active events plus the first 1–2 event names; truncates with "+N more".
- Tapping a day opens that week in week view (or a day-detail sheet if we want a third view later).
- Same status-styling rule for cancelled/deleted events.

### Add Event Page

The user's stated form fields:

1. **Event name** (text input, required)
2. **Start time** (datetime-local input, required) — date and time chosen together to match how the user thinks about it. Default to the next half-hour slot.
3. **Reminder times** — a list of reminder rows the user can add/remove. Each row offers a quick-pick (Day of, 1 hour before, 30 min before, Night before, Custom) plus a custom datetime field for "Custom". Defaults to two prefilled rows: "Day of" and "1 hour before" — matching the default in `scheduler_instructions.md`. The user can delete either to opt out, or add more.

Not in the form (because the user didn't list them, and they have safe defaults):

- **End time**: not prompted. The backend assumes `start + default_event_duration_minutes` from `config.json` (1 hour). An advanced toggle could reveal an explicit end-time field for power users.
- **Conflict check**: shown inline on the form (the page calls `/api/events?from=...&to=...` for the new event's time window and warns about overlaps, but does not block submission — matching the host agent's behavior).

On submit:

1. Validate inputs.
2. Compute `event_end` = `start + default_event_duration_minutes` if not specified.
3. Open the appropriate monthly workbook, write the event into the correct weekly sheet cell(s).
4. Append a row to `changelog.csv` with action `ADD` and details `"Added via mobile app"`.
5. For each reminder row, append an entry to `reminders.json` with `status: "active"`. If the user left the defaults, write the two default entries (day-of + 1h before) exactly the way `scheduler_instructions.md` prescribes.
6. Redirect to the week view containing the new event, with a flash message.

### Event Detail / Edit (out of scope for v1, but planned)

Tapping an event in any view opens a detail sheet with: name, time, reminders, status, "Cancel" and "Delete" buttons. Cancel sets `status: "cancelled"` on the event's reminder entries and rewrites the spreadsheet cell to `Event Name (cancelled)`. Delete does the same with `"deleted"`. Both append to changelog. v1 can ship without edit; the user already has the Telegram path for edits.

## Concurrency with the Host Agent and the Daemon

All three writers (the host agent, the daemon, the new web app) must respect the same file-locking convention already in `reminder_daemon.py`:

- `reminders.json`: use `fcntl.flock(LOCK_EX)` on write, `LOCK_SH` on read.
- `changelog.csv`: open in append mode with `LOCK_EX` for the duration of the write.
- Monthly xlsx files: workbook-level lock via a sibling `.lock` file (openpyxl is not safe for concurrent writes).

Reads are otherwise lock-free except for the shared lock above.

## Source of Truth for the Calendar

Two candidates:

1. **Spreadsheet** is the source of truth (matches today's model). The app reads weekly sheets and renders cells.
2. **reminders.json** is the source of truth. The app builds the calendar from reminder entries.

Recommendation: **option 1** for reads, **dual-write** on add. The spreadsheet is the human-editable record; `reminders.json` is operational. The weekly digest already trusts `reminders.json`, so we keep that. For UI rendering, parsing the weekly sheet is straightforward and produces what the user actually sees in their spreadsheet — including events the host agent may have written without a reminder, and including the `(cancelled)` / `(deleted)` annotations.

To avoid double-parsing the xlsx on every request, cache parsed weeks in memory with a mtime-based invalidation.

## Deployment

New systemd unit at `/etc/systemd/system/sando-web.service`:

```ini
[Unit]
Description=Sando Scheduler Web UI
After=network.target tailscaled.service

[Service]
Type=simple
User=<your_username>
WorkingDirectory=/home/Schedule
ExecStart=/usr/bin/python3 -m uvicorn sando_web.app:app --host <tailnet-ip> --port 8765
Restart=always
RestartSec=10
Environment=SCHEDULE_DIR=/home/Schedule

[Install]
WantedBy=multi-user.target
```

Binding to the tailnet IP (or `100.64.0.0/10` interface) instead of `0.0.0.0` ensures the port isn't reachable on the LAN.

## Phased Build

1. **v0.1 ✅** — Read-only weekly view served over Tailscale. Confirms file parsing + access model.
2. **v0.2 ✅** — Monthly view + day-detail tap-through.
3. **v0.3 ✅** — Add-event form, conflict warning, dual-write to xlsx + reminders.json + changelog.
4. **v0.4 ✅** — Event-detail sheet with Cancel / Delete actions.
5. **v0.5 ✅** — PWA polish (manifest, service worker, install prompt).

## Open Questions

- Should the app send a Telegram confirmation when an event is created, or stay silent? (Default: silent — the user is already in the app when they create the event.)
- Multi-device: the same Tailnet IP serves all the user's devices; no per-device state. OK?
- Auth beyond Tailscale: probably unnecessary for v1, but if the phone is ever shared we'd want a passcode on the app itself.
