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
