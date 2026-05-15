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
from datetime import datetime, timezone, timedelta, date
import requests

# --- Config ---
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
REMINDERS_FILE = os.environ.get("REMINDERS_FILE", "/home/Schedule/reminders.json")
STATE_FILE = os.environ.get(
    "DAEMON_STATE_FILE", "/home/Schedule/reminder_daemon_state.json"
)
POLL_INTERVAL = 60  # seconds
HST = timezone(timedelta(hours=-10))
LOG_FILE = "/home/Schedule/reminder_daemon.log"
PRUNE_AFTER_DAYS = 7

# Weekly summary settings. Sunday=6 in datetime.weekday() (Mon=0..Sun=6).
WEEKLY_SUMMARY_WEEKDAY = 6  # Sunday
WEEKLY_SUMMARY_HOUR = 8
WEEKLY_SUMMARY_MINUTE = 0

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def send_telegram(message: str):
    """Send a plain text message to the Scheduling chat."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logging.info(f"Sent message: {message[:80]}...")
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


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"Error reading state: {e}")
        return {}


def save_state(state: dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except IOError as e:
        logging.error(f"Error writing state: {e}")


def parse_remind_at(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HST)
    return dt


def check_and_send(now: datetime):
    """Find all due reminders and send them, coalescing simultaneous ones."""
    reminders = load_reminders()
    if not reminders:
        return

    due = []
    for entry in reminders:
        if entry.get("sent"):
            continue
        # Skip cancelled/deleted events but keep them in the file as history.
        if entry.get("status", "active") != "active":
            continue
        try:
            remind_at = parse_remind_at(entry["remind_at"])
        except (KeyError, ValueError) as e:
            logging.error(f"Bad remind_at in entry {entry.get('id', '?')}: {e}")
            continue
        if remind_at <= now:
            due.append(entry)

    changed = False

    if due:
        # Coalesce all reminders due in this poll cycle into a single message.
        if len(due) == 1:
            msg = due[0].get(
                "message", f"Reminder: {due[0].get('event_name', 'Event')}"
            )
        else:
            lines = ["Reminders:"]
            for entry in due:
                line = entry.get(
                    "message", f"Reminder: {entry.get('event_name', 'Event')}"
                )
                lines.append(f"- {line}")
            msg = "\n".join(lines)
        send_telegram(msg)
        for entry in due:
            entry["sent"] = True
        changed = True

    # Prune old reminders. Sent reminders, and cancelled/deleted reminders
    # whose event_date is past the retention window, are dropped from
    # reminders.json. Permanent history lives in changelog.csv.
    cutoff = now - timedelta(days=PRUNE_AFTER_DAYS)

    def is_stale(r: dict) -> bool:
        ev = r.get("event_date")
        if not ev:
            return False
        try:
            ev_dt = datetime.strptime(ev, "%Y-%m-%d").replace(tzinfo=HST)
        except ValueError:
            return False
        if ev_dt >= cutoff:
            return False
        return r.get("sent") or r.get("status", "active") != "active"

    before_count = len(reminders)
    reminders = [r for r in reminders if not is_stale(r)]
    if len(reminders) < before_count:
        changed = True

    if changed:
        save_reminders(reminders)


def format_event_line(event_date: date, event_name: str, event_start: str) -> str:
    weekday = event_date.strftime("%a")
    month_day = event_date.strftime("%b %-d")
    start = event_start or "TBD"
    return f"{weekday} {month_day} {start} — {event_name}"


def build_weekly_digest(reminders: list, week_start: date) -> str:
    """Build the Sunday digest message for the week starting `week_start`."""
    week_end = week_start + timedelta(days=6)
    seen = set()
    events = []
    for r in reminders:
        if r.get("status", "active") != "active":
            continue
        ev_date_str = r.get("event_date")
        ev_name = r.get("event_name")
        ev_start = r.get("event_start", "")
        if not ev_date_str or not ev_name:
            continue
        try:
            ev_date = datetime.strptime(ev_date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (week_start <= ev_date <= week_end):
            continue
        key = (ev_date, ev_name, ev_start)
        if key in seen:
            continue
        seen.add(key)
        events.append((ev_date, ev_start, ev_name))

    if not events:
        return (
            f"No events scheduled for the week of "
            f"{week_start.strftime('%b %-d')}."
        )

    events.sort(key=lambda e: (e[0], e[1]))
    lines = [f"Events this week ({week_start.strftime('%b %-d')}–"
             f"{week_end.strftime('%b %-d')}):"]
    for ev_date, ev_start, ev_name in events:
        lines.append(f"- {format_event_line(ev_date, ev_name, ev_start)}")
    return "\n".join(lines)


def maybe_send_weekly_digest(now: datetime, state: dict) -> dict:
    """If it's Sunday at/after the configured time and we haven't sent today's
    digest yet, send it."""
    if now.weekday() != WEEKLY_SUMMARY_WEEKDAY:
        return state
    if (now.hour, now.minute) < (WEEKLY_SUMMARY_HOUR, WEEKLY_SUMMARY_MINUTE):
        return state

    today_str = now.date().isoformat()
    if state.get("last_weekly_digest_date") == today_str:
        return state

    reminders = load_reminders()
    msg = build_weekly_digest(reminders, now.date())
    send_telegram(msg)
    state["last_weekly_digest_date"] = today_str
    save_state(state)
    return state


def main():
    logging.info("Reminder daemon started.")
    state = load_state()
    while True:
        try:
            now = datetime.now(HST)
            check_and_send(now)
            state = maybe_send_weekly_digest(now, state)
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
