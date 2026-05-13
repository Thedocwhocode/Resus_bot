import pathlib

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from resusbot.dashboard.auth import verify_dashboard_credentials
from resusbot.db.repository import (
    get_kpis,
    get_timeseries,
    get_top_articles,
    get_top_queries,
    get_top_subjects,
    get_top_users,
)
from resusbot.db.session import get_session

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_templates_dir = pathlib.Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


@router.get("", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    _user: str = Depends(verify_dashboard_credentials),
) -> HTMLResponse:
    return templates.TemplateResponse("dashboard.html", {"request": request})


# ── Partials HTML para HTMX ───────────────────────────────────────────────────

@router.get("/api/stats", response_class=HTMLResponse)
async def api_stats(
    request: Request,
    range: int = 7,
    _user: str = Depends(verify_dashboard_credentials),
    session=Depends(get_session),
) -> HTMLResponse:
    data = await get_kpis(session, days=range)
    return templates.TemplateResponse("partials/kpis.html", {"request": request, "data": data, "range": range})


@router.get("/api/top-users", response_class=HTMLResponse)
async def api_top_users(
    request: Request,
    limit: int = 10,
    _user: str = Depends(verify_dashboard_credentials),
    session=Depends(get_session),
) -> HTMLResponse:
    rows = await get_top_users(session, limit=limit)
    return templates.TemplateResponse("partials/top_users.html", {"request": request, "rows": rows})


@router.get("/api/top-subjects", response_class=HTMLResponse)
async def api_top_subjects(
    request: Request,
    limit: int = 10,
    _user: str = Depends(verify_dashboard_credentials),
    session=Depends(get_session),
) -> HTMLResponse:
    rows = await get_top_subjects(session, limit=limit)
    return templates.TemplateResponse("partials/top_subjects.html", {"request": request, "rows": rows})


@router.get("/api/top-queries", response_class=HTMLResponse)
async def api_top_queries(
    request: Request,
    limit: int = 10,
    _user: str = Depends(verify_dashboard_credentials),
    session=Depends(get_session),
) -> HTMLResponse:
    rows = await get_top_queries(session, limit=limit)
    return templates.TemplateResponse("partials/top_queries.html", {"request": request, "rows": rows})


@router.get("/api/top-articles", response_class=HTMLResponse)
async def api_top_articles(
    request: Request,
    limit: int = 10,
    _user: str = Depends(verify_dashboard_credentials),
    session=Depends(get_session),
) -> HTMLResponse:
    rows = await get_top_articles(session, limit=limit)
    return templates.TemplateResponse("partials/top_articles.html", {"request": request, "rows": rows})


@router.get("/api/timeseries")
async def api_timeseries(
    days: int = 30,
    _user: str = Depends(verify_dashboard_credentials),
    session=Depends(get_session),
) -> list:
    return await get_timeseries(session, days=days)
