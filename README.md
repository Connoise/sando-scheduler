# Sando Scheduler

A lightweight Python daemon that monitors a `reminders.json` file and sends Telegram messages at scheduled times. Runs as a systemd service on the host machine. No AI involved — purely a timer and message sender.

## Docs

- [`reminder_daemon_spec.md`](./reminder_daemon_spec.md) — Full specification for the daemon: logic, schema, systemd setup, and script skeleton.
- [`scheduler_instructions.md`](./scheduler_instructions.md) — Operating instructions for the host agent (Hermes) when handling scheduling tasks: file layout, defaults, cancel/delete semantics, reminder rules.
- [`mobile_app_plan.md`](./mobile_app_plan.md) — Design plan for the planned Tailscale-served mobile calendar app.

## Structure

```
sando-scheduler/
├── README.md
├── reminder_daemon_spec.md      ← daemon spec
├── scheduler_instructions.md    ← scheduling rules for the host agent
├── mobile_app_plan.md           ← planned mobile UI
├── reminder_daemon.py
├── reminder-daemon.service
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
- File-locked reads/writes to avoid race conditions with the host agent
- Coalesces reminders that fire in the same polling cycle into a single message
- Sends a Sunday-morning digest of the week's active events (excludes cancelled/deleted)

## Environment Variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token for the Telegram bot |
| `TELEGRAM_CHAT_ID` | Target Scheduling chat ID |
| `REMINDERS_FILE` | Path to `reminders.json` (default: `/home/Schedule/reminders.json`) |
