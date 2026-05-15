"""App config — paths, timezone, defaults loaded from config.json."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import timezone, timedelta
from pathlib import Path


HST = timezone(timedelta(hours=-10))

DEFAULT_CONFIG = {
    "default_event_duration_minutes": 60,
    "default_reminder_offsets": ["day_of", "1h_before"],
    "default_reminder_minutes": 60,
    "morning_time": "8:00 AM",
    "weekly_summary_day": "Sunday",
    "weekly_summary_time": "8:00 AM",
    "timezone": "HST",
    "time_format": "12h",
    "spreadsheet_format": "xlsx",
}


@dataclass(frozen=True)
class Settings:
    schedule_dir: Path
    reminders_file: Path
    changelog_file: Path
    config_file: Path
    archive_dir: Path
    defaults: dict = field(default_factory=lambda: dict(DEFAULT_CONFIG))

    @classmethod
    def from_env(cls) -> "Settings":
        schedule_dir = Path(
            os.environ.get("SCHEDULE_DIR", "/home/Schedule")
        ).expanduser()
        return cls(
            schedule_dir=schedule_dir,
            reminders_file=Path(
                os.environ.get(
                    "REMINDERS_FILE", str(schedule_dir / "reminders.json")
                )
            ),
            changelog_file=schedule_dir / "changelog.csv",
            config_file=schedule_dir / "config.json",
            archive_dir=schedule_dir / "Archive",
            defaults=load_defaults(schedule_dir / "config.json"),
        )

    def workbook_path(self, year: int, month_name: str) -> Path:
        return self.schedule_dir / str(year) / f"{year}_{month_name}.xlsx"


def load_defaults(config_path: Path) -> dict:
    if not config_path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with config_path.open("r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    if isinstance(data, dict):
        merged.update(data)
    return merged
