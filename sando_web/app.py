"""FastAPI app — v0.1: read-only weekly view served over Tailscale.

Routes follow `mobile_app_plan.md` §Routes. Only `/` and
`/week/{YYYY-MM-DD}` are wired up in v0.1; later phases will fill in
the month view and the add-event form.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .calendar_utils import WeekContext, week_dates
from .config import HST, Settings
from .schedule_io import (
    MonthView,
    WeeklySheetCache,
    WeeklySheetView,
    load_event_detail,
    load_events_in_range,
)
from .schedule_write import (
    ReminderSpec,
    build_default_reminder_specs,
    build_reminder_spec,
    update_event_status,
    write_event,
)


PACKAGE_DIR = Path(__file__).parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    cache = WeeklySheetCache()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    app = FastAPI(title="Sando Scheduler", version="0.1.0")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.state.settings = settings
    app.state.cache = cache

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        today = date.today()
        return RedirectResponse(url=f"/week/{today.isoformat()}", status_code=307)

    @app.get("/week/{cursor}")
    def week(cursor: str, request: Request):
        try:
            cursor_date = date.fromisoformat(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date (use YYYY-MM-DD)")
        ctx = WeekContext.for_date(cursor_date)
        workbook = settings.workbook_path(ctx.workbook_year, ctx.workbook_month)
        view = WeeklySheetView.build(ctx, workbook, cache)
        return templates.TemplateResponse(
            request,
            "week.html",
            {
                "view": view,
                "ctx": ctx,
                "week_dates": week_dates(ctx.start),
                "now": datetime.now(),
                "workbook_path": str(workbook),
                "month_link": f"/month/{ctx.workbook_year}-{ctx.start.month:02d}",
            },
        )

    @app.get("/month/{ym}")
    def month(ym: str, request: Request):
        try:
            year_str, month_str = ym.split("-", 1)
            year = int(year_str)
            month = int(month_str)
            if not (1 <= month <= 12):
                raise ValueError
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid month (use YYYY-MM)")
        view = MonthView.build(year, month, settings.schedule_dir, cache)
        return templates.TemplateResponse(
            request,
            "month.html",
            {
                "view": view,
                "today": date.today(),
            },
        )

    @app.get("/event/new")
    def event_new_form(request: Request, start: str | None = None):
        default_start = _default_form_start(start)
        return templates.TemplateResponse(
            request,
            "event_form.html",
            {
                "default_start": default_start,
                "default_duration_minutes": int(
                    settings.defaults.get("default_event_duration_minutes", 60)
                ),
                "default_reminder_offsets": settings.defaults.get(
                    "default_reminder_offsets", ["day_of", "1h_before"]
                ),
                "error": None,
            },
        )

    @app.post("/event")
    async def event_create(request: Request):
        form = await request.form()
        name = (form.get("event_name") or "").strip()
        start_raw = (form.get("start") or "").strip()
        duration_raw = (form.get("duration_minutes") or "").strip()

        try:
            start_dt = _parse_form_datetime(start_raw)
        except ValueError as e:
            return _form_error(templates, request, settings, form, str(e))
        if not name:
            return _form_error(templates, request, settings, form,
                               "Event name is required.")
        try:
            duration = int(duration_raw) if duration_raw else int(
                settings.defaults.get("default_event_duration_minutes", 60)
            )
        except ValueError:
            return _form_error(templates, request, settings, form,
                               "Duration must be a number.")
        if duration <= 0:
            return _form_error(templates, request, settings, form,
                               "Duration must be greater than zero.")
        end_dt = start_dt + timedelta(minutes=duration)

        specs = _collect_reminder_specs(form, start_dt, settings.defaults)

        write_event(
            event_name=name,
            start=start_dt,
            end=end_dt,
            schedule_dir=settings.schedule_dir,
            reminders_file=settings.reminders_file,
            changelog_file=settings.changelog_file,
            reminder_specs=specs,
        )
        # Bust the parse cache for the affected workbook(s).
        cache.clear()
        return RedirectResponse(
            url=f"/week/{start_dt.date().isoformat()}?flash=added",
            status_code=303,
        )

    @app.get("/event/{ev_date}/{name}")
    def event_detail(ev_date: str, name: str, request: Request):
        try:
            d = date.fromisoformat(ev_date)
        except ValueError:
            raise HTTPException(400, "Invalid date (use YYYY-MM-DD)")
        detail = load_event_detail(
            name, d, settings.schedule_dir, settings.reminders_file, cache
        )
        if detail is None:
            raise HTTPException(404, "Event not found")
        return templates.TemplateResponse(
            request,
            "event_detail.html",
            {
                "detail": detail,
                "week_link": f"/week/{d.isoformat()}",
                "back_link": request.query_params.get("back") or f"/week/{d.isoformat()}",
            },
        )

    @app.post("/event/{ev_date}/{name}/{action}")
    def event_action(ev_date: str, name: str, action: str):
        if action == "cancel":
            new_status = "cancelled"
        elif action == "delete":
            new_status = "deleted"
        else:
            raise HTTPException(404, "Unknown action")
        try:
            d = date.fromisoformat(ev_date)
        except ValueError:
            raise HTTPException(400, "Invalid date (use YYYY-MM-DD)")
        changed = update_event_status(
            event_name=name,
            event_date=d,
            new_status=new_status,
            schedule_dir=settings.schedule_dir,
            reminders_file=settings.reminders_file,
            changelog_file=settings.changelog_file,
        )
        if changed == 0:
            raise HTTPException(404, "Event not found")
        cache.clear()
        flash = "cancelled" if new_status == "cancelled" else "deleted"
        return RedirectResponse(
            url=f"/week/{d.isoformat()}?flash={flash}", status_code=303,
        )

    @app.get("/api/events")
    def api_events(request: Request):
        # `from` is a Python keyword, so read from query params directly.
        from_ = request.query_params.get("from")
        to = request.query_params.get("to")
        if not from_ or not to:
            raise HTTPException(400, "from and to are required (YYYY-MM-DD)")
        try:
            d_from = date.fromisoformat(from_)
            d_to = date.fromisoformat(to)
        except ValueError:
            raise HTTPException(400, "Invalid date (use YYYY-MM-DD)")
        events = load_events_in_range(d_from, d_to, settings.schedule_dir, cache)
        return JSONResponse([
            {
                "date": e.date.isoformat(),
                "slot": e.slot.isoformat(timespec="minutes"),
                "slot_label": e.slot_label,
                "name": e.name,
                "status": e.status,
            }
            for e in events
        ])

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(
            STATIC_DIR / "manifest.webmanifest",
            media_type="application/manifest+json",
        )

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        # The SW must be served from the URL it should control (the root)
        # and with an explicit JS MIME so browsers register it. Disable
        # caching so updates roll out on the next page load.
        return FileResponse(
            STATIC_DIR / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache",
                     "Service-Worker-Allowed": "/"},
        )

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok", "schedule_dir": str(settings.schedule_dir)}

    return app


# --- Form helpers --------------------------------------------------------

def _default_form_start(start_param: str | None) -> str:
    """Render a value for <input type="datetime-local">.

    HTML datetime-local uses 'YYYY-MM-DDTHH:MM' (no tz). Default is the
    next half-hour slot.
    """
    if start_param:
        try:
            # Accept either a date or a full datetime-local string.
            if "T" in start_param:
                datetime.fromisoformat(start_param)
                return start_param
            d = date.fromisoformat(start_param)
            return f"{d.isoformat()}T09:00"
        except ValueError:
            pass
    now = datetime.now(HST).replace(second=0, microsecond=0, tzinfo=None)
    minute = 30 if now.minute < 30 else 0
    if minute == 0:
        now = now.replace(minute=0) + timedelta(hours=1)
    else:
        now = now.replace(minute=30)
    return now.strftime("%Y-%m-%dT%H:%M")


def _parse_form_datetime(value: str) -> datetime:
    """Parse 'YYYY-MM-DDTHH:MM' from datetime-local and attach HST."""
    if not value:
        raise ValueError("Start time is required.")
    try:
        naive = datetime.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f"Invalid start time: {value}") from e
    return naive.replace(tzinfo=HST)


def _form_error(templates, request, settings, form, message):
    return templates.TemplateResponse(
        request,
        "event_form.html",
        {
            "default_start": form.get("start") or _default_form_start(None),
            "default_duration_minutes": int(
                settings.defaults.get("default_event_duration_minutes", 60)
            ),
            "default_reminder_offsets": settings.defaults.get(
                "default_reminder_offsets", ["day_of", "1h_before"]
            ),
            "error": message,
            "submitted_name": form.get("event_name", ""),
        },
        status_code=400,
    )


def _collect_reminder_specs(form, start_dt: datetime, defaults: dict
                            ) -> list[ReminderSpec]:
    """Build ReminderSpec list from the form's repeated `reminder` fields."""
    from .schedule_write import _parse_clock_label
    kinds = form.getlist("reminder")
    if not kinds:
        return build_default_reminder_specs(start_dt, defaults)
    morning = (_parse_clock_label(defaults.get("morning_time", "8:00 AM"))
               or _parse_clock_label("8:00 AM"))
    customs = form.getlist("reminder_custom")
    out: list[ReminderSpec] = []
    custom_iter = iter(customs)
    for kind in kinds:
        custom_dt: datetime | None = None
        if kind == "custom":
            raw = next(custom_iter, "")
            if raw:
                try:
                    custom_dt = datetime.fromisoformat(raw).replace(tzinfo=HST)
                except ValueError:
                    custom_dt = None
        spec = build_reminder_spec(kind, start_dt, morning, custom_dt)
        if spec is not None:
            out.append(spec)
    return out


# Module-level instance for `uvicorn sando_web.app:app`.
app = create_app()
