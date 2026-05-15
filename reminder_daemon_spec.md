# reminder_daemon.py — Companion Reminder Script Specification

## Overview

This is a lightweight, non-AI Python script that runs as a systemd service on the host machine (Lenovo ThinkCentre). It monitors `/home/Schedule/reminders.json` and sends Telegram messages at scheduled times. It does **not** invoke Claude or any AI API — it is purely a timer and message sender.

## Dependencies

```
pip install python-telegram-bot schedule
```

## Environment Variables

Set these in the systemd service file or a `.env` file:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token for the scheduling Telegram bot |
| `TELEGRAM_CHAT_ID` | Chat ID of the "Scheduling" group chat |
| `REMINDERS_FILE` | Path to `reminders.json` (default: `/home/Schedule/reminders.json`) |

## Logic

```
Every 60 seconds:
  1. Read reminders.json
  2. Collect every entry where sent == false AND status == "active"
     (default when status is missing) AND remind_at <= now
  3. If 1 entry is due: send its message
     If 2+ entries are due in the same poll cycle: coalesce them into a
     single Telegram message with one line per reminder ("Reminders:\n- ...")
  4. Mark every sent entry sent = true
  5. Write updated reminders.json back (only if changes were made)
  6. Prune entries whose event_date is older than 7 days when either
     sent == true OR status is "cancelled"/"deleted". Cancelled and
     deleted events remain in the file until they age out — their
     permanent history lives in changelog.csv.
  7. Weekly digest: if today is Sunday and current time >= 8:00 AM HST and
     we have not already sent today's digest (tracked in
     reminder_daemon_state.json), build a summary of all events with
     event_date in [today, today+6] and status == "active" from
     reminders.json and send it. Cancelled and deleted events are
     excluded. If no active events fall in that range, send a
     "no events scheduled for the week" message.
```

## Key Design Notes

- **Polling interval: 60 seconds.** This is cheap (no API calls, just file reads) and accurate enough for scheduling purposes. A reminder set for 1:00 PM will fire between 1:00 PM and 1:01 PM.
- **File locking**: Use a simple file lock (`fcntl.flock` or a `.lock` file) to avoid race conditions if the host agent writes to `reminders.json` at the same moment the daemon reads it.
- **Timezone**: All `remind_at` values are in HST (UTC-10). Parse accordingly.
- **Error handling**: If `reminders.json` is malformed or missing, log the error and retry on next cycle. Do not crash.
- **Logging**: Write to `/home/Schedule/reminder_daemon.log` with timestamps. Log each reminder sent and any errors.

## systemd Service

Create `/etc/systemd/system/reminder-daemon.service`:

```ini
[Unit]
Description=Sando Schedule Reminder Daemon
After=network.target

[Service]
Type=simple
User=<your_username>
WorkingDirectory=/home/Schedule
ExecStart=/usr/bin/python3 /home/Schedule/reminder_daemon.py
Restart=always
RestartSec=10
Environment=TELEGRAM_BOT_TOKEN=<token>
Environment=TELEGRAM_CHAT_ID=<chat_id>
Environment=REMINDERS_FILE=/home/Schedule/reminders.json

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable reminder-daemon.service
sudo systemctl start reminder-daemon.service
```

## Script Skeleton

```python
#!/usr/bin/env python3
"""
reminder_daemon.py
Watches reminders.json and sends Telegram messages at scheduled times.
No AI involved — just a file watcher and message sender.
"""

import json
import os
import time
import logging
import fcntl
from datetime import datetime, timezone, timedelta
import requests

# --- Config ---
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
REMINDERS_FILE = os.environ.get("REMINDERS_FILE", "/home/Schedule/reminders.json")
POLL_INTERVAL = 60  # seconds
HST = timezone(timedelta(hours=-10))
LOG_FILE = "/home/Schedule/reminder_daemon.log"
PRUNE_AFTER_DAYS = 7

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

def send_telegram(message: str):
    """Send a plain text message to the Scheduling chat."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logging.info(f"Sent reminder: {message[:80]}...")
    except Exception as e:
        logging.error(f"Failed to send message: {e}")

def load_reminders() -> list:
    """Read reminders.json with file locking."""
    if not os.path.exists(REMINDERS_FILE):
        return []
    try:
        with open(REMINDERS_FILE, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"Error reading reminders: {e}")
        return []

def save_reminders(reminders: list):
    """Write reminders.json with file locking."""
    try:
        with open(REMINDERS_FILE, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(reminders, f, indent=2)
            fcntl.flock(f, fcntl.LOCK_UN)
    except IOError as e:
        logging.error(f"Error writing reminders: {e}")

def check_and_send():
    """Main loop iteration: check for due reminders and send them."""
    reminders = load_reminders()
    if not reminders:
        return

    now = datetime.now(HST)
    changed = False

    for entry in reminders:
        if entry.get("sent"):
            continue

        try:
            remind_at = datetime.fromisoformat(entry["remind_at"])
            if remind_at.tzinfo is None:
                remind_at = remind_at.replace(tzinfo=HST)
        except (KeyError, ValueError) as e:
            logging.error(f"Bad remind_at in entry {entry.get('id', '?')}: {e}")
            continue

        if remind_at <= now:
            send_telegram(entry.get("message", f"Reminder: {entry.get('event_name', 'Event')}"))
            entry["sent"] = True
            changed = True

    # Prune old sent reminders
    cutoff = now - timedelta(days=PRUNE_AFTER_DAYS)
    before_count = len(reminders)
    reminders = [
        r for r in reminders
        if not (
            r.get("sent")
            and r.get("event_date")
            and datetime.strptime(r["event_date"], "%Y-%m-%d").replace(tzinfo=HST) < cutoff
        )
    ]
    if len(reminders) < before_count:
        changed = True

    if changed:
        save_reminders(reminders)

def main():
    logging.info("Reminder daemon started.")
    while True:
        try:
            check_and_send()
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
```

## Notes for the Host Agent (see `scheduler_instructions.md`)

- The host agent writes to `reminders.json` — this script reads it.
- The host agent sets `sent: false` and `status: "active"` on new entries — this script sets `sent: true` after delivery and skips entries whose `status` is not `"active"`.
- On cancellation the host agent sets `status: "cancelled"` (not removal); on deletion it sets `status: "deleted"`. This script prunes those entries 7 days after the event date — permanent history lives in `changelog.csv`.
- This script never modifies the spreadsheet or changelog — those are the host agent's domain.
- If this script is offline, reminders will fire the next time it starts (any past-due unsent active reminders will be sent immediately on restart, coalesced into one message).
