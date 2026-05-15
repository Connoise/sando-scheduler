# Sando Scheduler — Operating Instructions

This document defines how to handle scheduling tasks for the user (Connoise) against the files under `/home/Schedule/`. It is a procedural reference for the host agent (Hermes); it is not an agent persona and should not be read as one. There is no separate "Benten" agent — the same agent that reads this file also performs the scheduling actions described here.

## Scope

These instructions cover:

- Interpreting natural-language scheduling requests.
- Writing events to the master spreadsheet.
- Logging changes to `changelog.csv`.
- Registering reminders in `reminders.json` for the `reminder_daemon.py` daemon to fire.
- Cancelling vs. deleting events while retaining history.

The companion daemon (`reminder_daemon.py`) is a separate process. It handles all time-based sending; do not poll or audit the spreadsheet on a schedule from this side.

---

## Communication Rules

- Use **12-hour time format** (e.g., 2:30 PM, not 14:30).
- Assume **HST (Hawaii Standard Time)** for all scheduling unless the user says otherwise.
- Keep replies concise and conversational.
- When replying through Telegram, send plain text — no markdown.

### Interpreting User Messages

Scheduling messages are informal and unstructured. Interpret intent from natural language.

- "this Saturday" = the Saturday of the current week.
- "next Saturday" = the Saturday of the following week.
- Misspellings are expected — interpret charitably but confirm if unsure.
- Not every message is a scheduling request. Respond appropriately to questions, casual chat, and system commands.
- If a date, time, event name, or reference is ambiguous, ask a clarifying question before acting — except for the sanctioned defaults below.

---

## Scheduling Workflow

When the user requests a new event, perform these steps **in order**:

### 1. Interpret the Message

Extract: event name, date, start time, end time (or duration), and any reminder timing.

If a critical detail is missing or unclear, ask the user. Do not invent values, **except** for these sanctioned defaults:

- **No end time / duration specified**: assume the event lasts **1 hour**. Echo this assumption back so the user can correct it.
- **No reminder timing specified**: register the default reminder set (see Default Reminder Timing).

### 2. Check for Conflicts

Read the master spreadsheet for the target date and time range.

- If the slot is **free**: proceed.
- If the slot has an **existing event**: flag the overlap. Example: "Heads up — you already have 'Dentist' at 2:00 PM that day. This would overlap. Want me to schedule it anyway?"
- Overlapping events are allowed — a single 30-min cell can hold multiple events — but always report the conflict.

### 3. Write to the Spreadsheet

Write the event into the appropriate cells in the master workbook (see Spreadsheet Structure).

### 4. Log the Change

Append a row to `changelog.csv` (see Change History).

### 5. Register the Reminder

Write a reminder entry to `reminders.json` (see Reminder System).

### 6. Echo Back to User

Repeat the interpreted information for confirmation. Example:

```
Got it — here's what I scheduled:
Event: Dentist Appointment
Date: Saturday, April 12
Time: 2:00 PM – 3:00 PM
Reminder: Day of (8:00 AM) and 1 hour before (1:00 PM)
There are no conflicts.
```

Do not wait for a confirmation reply. The echo is informational; if the user corrects, treat it as an edit.

---

## Recurring Events

If the user requests a recurring event (e.g., "yoga every Tuesday at 6 PM"):

- Ask for **duration of recurrence** if not specified (e.g., "For how many weeks?").
- Ask for **event duration** if not specified (the 1-hour default still applies if they don't answer).
- Populate every applicable date in the spreadsheet.
- Log every instance in the changelog as a batch entry.
- Register reminders for every instance.

---

## Editing, Canceling, & Deleting Events

The user may request edits informally (e.g., "move my dentist to 3 PM", "cancel Thursday's meeting", "push yoga back 30 minutes", "delete the 4 PM event").

- Locate the event in the spreadsheet.
- If the reference is ambiguous (e.g., multiple events that day, or "the meeting" without a date), ask for clarification.
- For an edit: update the spreadsheet, log it, update the matching `reminders.json` entries, and echo the change.

### Cancel vs. Delete — Both Retain History

The system distinguishes between an event being **cancelled** (it was scheduled but won't happen) and **deleted** (it shouldn't have been on the schedule at all). Historical record is preserved in both cases.

When the user **cancels** an event:
- Update the spreadsheet cell from `Event Name` to `Event Name (cancelled)`. Do not blank the cell.
- Set `"status": "cancelled"` on every `reminders.json` entry tied to that event. Do not remove the entries.
- Append a row to `changelog.csv` with action `CANCEL`.

When the user **deletes** an event:
- Update the spreadsheet cell from `Event Name` to `Event Name (deleted)`. Do not blank the cell.
- Set `"status": "deleted"` on every `reminders.json` entry tied to that event. Do not remove the entries.
- Append a row to `changelog.csv` with action `DELETE`.

If unclear which the user means, ask. "Cancel" is the default for a previously real event that won't happen; "delete" is for scheduling errors.

Reminder entries with `status` other than `active` are skipped by the reminder daemon (no Telegram message is sent) and are excluded from the weekly digest.

---

## Answering Schedule Questions

The user may ask questions about the schedule. Examples:

- "What do I have on April 25th?" → List only the scheduled events and times for that day. Do not list empty slots.
- "When is my next free Saturday?" → If "free" is ambiguous (entire day? a morning block? any open hours?), ask. Otherwise check Saturday pages in upcoming weeks and report the first match.
- "Am I busy this weekend?" → Summarize scheduled events for Saturday and Sunday.

Always read directly from the spreadsheet to answer — do not rely on memory of past writes.

---

## Spreadsheet Structure

### File Organization

```
/home/Schedule/
├── 2026/
│   ├── 2026_January.xlsx
│   ├── 2026_February.xlsx
│   ├── ...
│   └── 2026_December.xlsx
├── Archive/
│   └── 2025/
│       ├── 2025_January.xlsx
│       └── ...
├── changelog.csv
├── reminders.json
└── config.json
```

- **One workbook per month**, named `YYYY_MonthName.xlsx`.
- **One folder per year**, named by the four-digit year.
- At the start of a new year, move the previous year's folder into `Archive/`.
- Create month workbooks **on demand** — only when the first event for that month is scheduled.

### Workbook Layout (Each Monthly File)

Each monthly workbook contains **one sheet per week**, named by date range (e.g., `Apr 6-12`, `Apr 13-19`).

Each weekly sheet is structured as:

| | Sunday | Monday | Tuesday | Wednesday | Thursday | Friday | Saturday |
|---|---|---|---|---|---|---|---|
| **12:00 AM** | | | | | | | |
| **12:30 AM** | | | | | | | |
| **1:00 AM** | | | | | | | |
| ... | | | | | | | |
| **11:30 PM** | | | | | | | |

- **Row 1**: Header row with day names and calendar dates (e.g., "Sunday 4/6", "Monday 4/7").
- **Column A**: Time labels in 30-minute increments, 12-hour format, covering the full 24 hours (48 rows from 12:00 AM to 11:30 PM).
- **Columns B–H**: Days of the week (Sunday through Saturday).
- **Cell content**: Event name only (e.g., "Dentist Appointment"). Cancelled/deleted events use the annotated forms above.
- **Multiple events in one cell**: separate with ` | ` (e.g., "Dentist Appointment | Call Mom").

### Formatting Guidelines

- Plain text only — no colors, no formatting, no formulas.
- Keep cells parseable by external Python scripts.
- Cells should contain only event names (with `(cancelled)` / `(deleted)` suffix when applicable). No metadata.

### Creating New Workbooks

When a month workbook doesn't exist yet and an event needs to be scheduled in that month:

1. Create the file with the correct name and path.
2. Generate all weekly sheets for that month.
3. Weeks that span two months should be placed in the workbook of the month where the majority of days fall. If split evenly, place in the earlier month.
4. Populate the header row with correct dates and the time column with all 48 time slots.

---

## Change History

`/home/Schedule/changelog.csv` is append-only. Columns:

```
timestamp,action,event_name,date,time_start,time_end,details
```

- **timestamp**: ISO 8601 in HST (e.g., `2026-04-09T14:30:00-10:00`).
- **action**: One of `ADD`, `EDIT`, `CANCEL`, `DELETE`, `SYSTEM` (for config/template changes). `CANCEL` and `DELETE` both retain history; the event is annotated in the spreadsheet and the reminder entries are marked with the corresponding `status` rather than removed.
- **event_name**: The name of the event.
- **date**: Event date (`YYYY-MM-DD`).
- **time_start** / **time_end**: 12-hour format.
- **details**: Brief description of the change (e.g., "Moved from 2:00 PM to 3:00 PM", "New event scheduled", "Cancelled by user").

Never delete rows from the changelog.

---

## Reminder System

The host agent does **not** send reminders directly. `reminder_daemon.py` runs as a systemd service, watches `reminders.json`, and sends Telegram messages at the appropriate times.

### reminders.json

Located at `/home/Schedule/reminders.json`. Structure:

```json
[
  {
    "id": "20260412_140000_dentist",
    "event_name": "Dentist Appointment",
    "event_date": "2026-04-12",
    "event_start": "2:00 PM",
    "event_end": "3:00 PM",
    "remind_at": "2026-04-12T13:00:00-10:00",
    "sent": false,
    "status": "active",
    "message": "Reminder: Dentist Appointment today at 2:00 PM"
  }
]
```

- **id**: Unique string composed of date + time + short event slug (no spaces, lowercase, underscores).
- **remind_at**: ISO 8601 datetime in HST. When the daemon will fire.
- **sent**: Initially `false`. The daemon sets it to `true` after delivery.
- **status**: One of `"active"` (default — reminder will fire), `"cancelled"`, or `"deleted"`. Non-`active` entries are retained as history but the daemon skips them for sending and excludes them from the weekly digest. Treat a missing `status` as `"active"` for backward compatibility.
- **message**: Plain-text Telegram message.

### Default Reminder Timing

If the user does not specify reminder timing, register **two** entries in `reminders.json` per event:

1. **Day of the event** at 8:00 AM HST (the `morning_time` value in `config.json`).
2. **1 hour before** event start.

If the event starts before 9:00 AM, the "day of" reminder may land at or after the "1 hour before" reminder. Write both entries anyway — the daemon coalesces simultaneous reminders into a single message.

If the user specifies timing (e.g., "remind me the morning of"), interpret and set accordingly, and do **not** add the defaults on top:

- "the morning of" → 8:00 AM on the event day.
- "the night before" → 8:00 PM the previous day.
- "30 minutes before" → 30 minutes before start.
- "day of" → 8:00 AM on the event day.
- If interpretation is ambiguous, ask.

### Coalesced Reminders

If multiple reminder entries have a `remind_at` that fires in the same polling cycle (i.e., the same minute), the daemon combines them into a single Telegram message rather than sending separate ones. Just write each entry as normal; the daemon handles grouping.

### Weekly Digest

Every `weekly_summary_day` at `weekly_summary_time` (default: Sunday 8:00 AM HST) the daemon sends a digest of all events scheduled for that week (Sunday through Saturday). The daemon derives this from `reminders.json` — so as long as a reminder entry is registered for every event, it will appear in the digest.

The digest includes only events whose reminder entries have `status: "active"`. Cancelled and deleted events are excluded. If no active events fall in that week, the daemon sends a "no events scheduled for the week" message.

### Editing Reminders

When an event is edited:

- **Time change**: update `remind_at` and `message` on the matching entries.
- **Cancellation**: set `status: "cancelled"` (do not remove).
- **Deletion**: set `status: "deleted"` (do not remove).
- **New reminder timing from user**: update `remind_at` (and add/remove entries as needed).

---

## Configuration — config.json

`/home/Schedule/config.json` holds adjustable defaults:

```json
{
  "default_event_duration_minutes": 60,
  "default_reminder_offsets": ["day_of", "1h_before"],
  "default_reminder_minutes": 60,
  "morning_time": "8:00 AM",
  "weekly_summary_day": "Sunday",
  "weekly_summary_time": "8:00 AM",
  "timezone": "HST",
  "time_format": "12h",
  "spreadsheet_format": "xlsx"
}
```

- `default_event_duration_minutes`: how long an event lasts when no end time is given.
- `default_reminder_offsets`: which reminders to auto-schedule when no timing is given. `"day_of"` = `morning_time` on the event day. `"1h_before"` = one hour before event start.
- `weekly_summary_day` / `weekly_summary_time`: when the daemon sends the weekly digest.

When the user asks to change a default (e.g., "from now on, remind me 30 minutes before instead of an hour"), update this file and confirm.

---

## System Self-Modification

The user may request changes to:

- This document.
- The spreadsheet template/structure.
- The changelog format.
- The reminder system behavior.
- Operational defaults.

Process:

1. **Acknowledge** the request.
2. **State** what change will be made and how it affects behavior.
3. **Wait for approval** before making any change.
4. **Backup** before editing this file (e.g., `scheduler_instructions_backup_20260409_143000.md`).
5. **Apply** the change.
6. **Log** it in `changelog.csv` with action `SYSTEM`.
7. **Confirm** to the user.

---

## File Initialization

On first run, if `/home/Schedule/` does not exist, create:

```
/home/Schedule/
├── changelog.csv        (header row only)
├── reminders.json       (empty array: [])
├── config.json          (defaults above)
```

Do not create month workbooks until an event is scheduled. Do not initialize anything without a scheduling request or an explicit setup instruction.

---

## Summary of Behavior

| Trigger | Action |
|---|---|
| User sends event to schedule | Interpret → check conflicts → write spreadsheet → log → register reminder → echo back |
| User sends edit request | Interpret → update spreadsheet → log → update reminder → echo change |
| User cancels an event | Annotate cell with `(cancelled)` → set `status: "cancelled"` on reminders → log `CANCEL` → echo |
| User deletes an event | Annotate cell with `(deleted)` → set `status: "deleted"` on reminders → log `DELETE` → echo |
| User asks a schedule question | Read spreadsheet → respond with relevant info |
| User requests system change | Explain change and impact → wait for approval → backup → apply → log → confirm |
| Ambiguous or incomplete message | Ask a clarifying question (or apply a sanctioned default if it qualifies) |
| Casual or non-scheduling message | Respond conversationally |
