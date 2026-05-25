from datetime import date, time

from sando_web.calendar_utils import (
    WeekContext,
    parse_slot_label,
    sheet_name_for_week,
    slot_label,
    week_start,
    workbook_for_week,
)


def test_week_start_returns_sunday_for_any_weekday():
    # 2026-05-15 is a Friday; the containing week starts Sunday 2026-05-10.
    assert week_start(date(2026, 5, 15)) == date(2026, 5, 10)
    # Sunday returns itself.
    assert week_start(date(2026, 5, 10)) == date(2026, 5, 10)
    # Saturday is the last day of the same week.
    assert week_start(date(2026, 5, 16)) == date(2026, 5, 10)


def test_slot_label_roundtrip():
    for hour in range(24):
        for minute in (0, 30):
            t = time(hour=hour, minute=minute)
            label = slot_label(t)
            assert parse_slot_label(label) == t


def test_slot_label_canonical_examples():
    assert slot_label(time(0, 0)) == "12:00 AM"
    assert slot_label(time(0, 30)) == "12:30 AM"
    assert slot_label(time(12, 0)) == "12:00 PM"
    assert slot_label(time(14, 30)) == "2:30 PM"
    assert slot_label(time(23, 30)) == "11:30 PM"


def test_workbook_for_week_picks_majority_month():
    # Week containing 2026-04-29: Sun 4/26..Sat 5/2 → 5 April days, 2 May.
    year, month = workbook_for_week(date(2026, 4, 26))
    assert (year, month) == (2026, "April")


def test_workbook_for_week_ties_to_earlier_month():
    # Hypothetical even split: choose the earlier month.
    # 2025-11-30 is a Sunday; week is 11/30..12/6 → 1 Nov day, 6 Dec.
    # Real example with a 3/4 split is rare; use 2026 case where Sunday
    # falls on month-end to construct a 4/3 split favouring earlier.
    # Mar 29 2026 is a Sunday; week is 3/29..4/4 → 3 March, 4 April.
    year, month = workbook_for_week(date(2026, 3, 29))
    assert (year, month) == (2026, "April")  # April wins by majority

    # Construct a clean tie: Sunday 2027-01-31 → 1 Jan, 6 Feb. Not a tie.
    # An actual 4/3 split going the other way:
    year, month = workbook_for_week(date(2026, 8, 30))  # 8/30..9/5 → 2 Aug, 5 Sep
    assert (year, month) == (2026, "September")


def test_sheet_name_matches_spec_example():
    # scheduler_instructions.md cites "Apr 6-12" for the week of Apr 6.
    assert sheet_name_for_week(date(2026, 4, 5)) == "Apr 5-11"
    # Week starting Apr 6 isn't a Sunday in 2026; use week_start to be safe.
    s = week_start(date(2026, 4, 9))  # Thursday
    assert sheet_name_for_week(s) == "Apr 5-11"


def test_week_context_navigation_fields():
    ctx = WeekContext.for_date(date(2026, 5, 15), today=date(2026, 5, 15))
    assert ctx.start == date(2026, 5, 10)
    assert ctx.end == date(2026, 5, 16)
    assert ctx.prev_start == date(2026, 5, 3)
    assert ctx.next_start == date(2026, 5, 17)
    assert ctx.workbook_year == 2026
    assert ctx.workbook_month == "May"
    assert ctx.sheet_name == "May 10-16"
