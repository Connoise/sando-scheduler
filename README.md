# Sando Scheduler

A lightweight Python daemon that monitors a `reminders.json` file and sends Telegram messages at scheduled times. Runs as a systemd service on the host machine. No AI involved — purely a timer and message sender.

## Docs

- [`reminder_daemon_spec.md`](./reminder_daemon_spec.md) — Full specification for the daemon: logic, schema, systemd setup, and script skeleton.

## Structure

```
sando-scheduler/
├── README.md
├── reminder_daemon_spec.md   ← start here
├── .gitignore
├── requirements.txt
└── scheduler/
    └── __init__.py
```

## Quick Start

See `reminder_daemon_spec.md` for full details. TL;DR:

1. Set env vars: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `REMINDERS_FILE`
2. Install deps: `pip install requests`
3. Run or deploy as a systemd service

## Key Design

- Polls `reminders.json` every 60s
- Sends Telegram message when `remind_at <= now` and `sent == false`
- Marks entry `sent: true` after delivery
- Prunes entries older than 7 days
- File-locked reads/writes to avoid race conditions with Benten

## Environment Variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token for the Telegram bot |
| `TELEGRAM_CHAT_ID` | Target Scheduling chat ID |
| `REMINDERS_FILE` | Path to `reminders.json` (default: `/home/Schedule/reminders.json`) |
