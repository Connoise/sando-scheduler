"""Pure calendar helpers: week boundaries, slot labels, month workbook routing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterator


MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Spreadsheet convention from scheduler_instructions.md: columns are
# Sunday..Saturday (B..H), so the week starts on Sunday.
WEEK_START_WEEKDAY = 6  # Mon=0..Sun=6


def week_start(d: date) -> date:
    """Return the Sunday on or before `d`."""
    days_since_sunday = (d.weekday() - WEEK_START_WEEKDAY) % 7
    return d - timedelta(days=days_since_sunday)


def week_dates(d: date) -> list[date]:
    """Seven dates Sunday..Saturday containing `d`."""
    start = week_start(d)
    return [start + timedelta(days=i) for i in range(7)]


def half_hour_slots() -> Iterator[time]:
    """All 48 half-hour slots of a day, 12:00 AM through 11:30 PM."""
    for i in range(48):
        yield time(hour=i // 2, minute=(i % 2) * 30)


def slot_label(t: time) -> str:
    """12-hour label matching the spreadsheet's column A (e.g. '2:30 PM')."""
    hour = t.hour % 12 or 12
    ampm = "AM" if t.hour < 12 else "PM"
    return f"{hour}:{t.minute:02d} {ampm}"


def parse_slot_label(label: str) -> time | None:
    """Inverse of slot_label. Returns None if the cell is unparseable."""
    label = label.strip()
    try:
        return datetime.strptime(label, "%I:%M %p").time()
    except ValueError:
        return None


def workbook_for_week(week_start_date: date) -> tuple[int, str]:
    """Pick (year, month_name) for the workbook that holds a week.

    Per scheduler_instructions.md §"Creating New Workbooks": weeks
    spanning two months live in the workbook of the month where the
    majority of days fall; ties go to the earlier month.
    """
    counts: dict[tuple[int, int], int] = {}
    for i in range(7):
        d = week_start_date + timedelta(days=i)
        counts[(d.year, d.month)] = counts.get((d.year, d.month), 0) + 1
    # Sort by (-count, year, month) so largest count wins; ties go to earlier.
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    (year, month), _ = ordered[0]
    return year, MONTH_NAMES[month - 1]


def sheet_name_for_week(week_start_date: date) -> str:
    """Match the spreadsheet's per-week sheet name, e.g. 'Apr 6-12'.

    When a week spans two months the end day is prefixed with the end
    month abbreviation, e.g. 'Jun 28-Jul 4', matching the actual
    spreadsheet convention for cross-month weeks.
    """
    end = week_start_date + timedelta(days=6)
    start_abbr = week_start_date.strftime("%b")
    if end.month != week_start_date.month:
        end_abbr = end.strftime("%b")
        return f"{start_abbr} {week_start_date.day}-{end_abbr} {end.day}"
    return f"{start_abbr} {week_start_date.day}-{end.day}"


@dataclass(frozen=True)
class WeekContext:
    """Everything a view needs to navigate from one week."""

    today: date
    cursor: date
    start: date
    end: date
    prev_start: date
    next_start: date
    workbook_year: int
    workbook_month: str
    sheet_name: str

    @classmethod
    def for_date(cls, cursor: date, today: date | None = None) -> "WeekContext":
        start = week_start(cursor)
        year, month = workbook_for_week(start)
        return cls(
            today=today or date.today(),
            cursor=cursor,
            start=start,
            end=start + timedelta(days=6),
            prev_start=start - timedelta(days=7),
            next_start=start + timedelta(days=7),
            workbook_year=year,
            workbook_month=month,
            sheet_name=sheet_name_for_week(start),
        )
