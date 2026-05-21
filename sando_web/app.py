"""FastAPI app — v0.1: read-only weekly view served over Tailscale.

Routes follow `mobile_app_plan.md` §Routes. Only `/` and
`/week/{YYYY-MM-DD}` are wired up in v0.1; later phases will fill in
the month view and the add-event form.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .calendar_utils import WeekContext, week_dates
from .config import Settings
from .schedule_io import MonthView, WeeklySheetCache, WeeklySheetView


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

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok", "schedule_dir": str(settings.schedule_dir)}

    return app


# Module-level instance for `uvicorn sando_web.app:app`.
app = create_app()
