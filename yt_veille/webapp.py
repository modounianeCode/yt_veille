"""Interface web (FastAPI + Jinja2 + HTMX).

Un seul service sert :
- les pages HTML ;
- quelques routes JSON sous /api ;
- la documentation interactive sous /docs.

Lancement :  yt-veille serve   →  http://127.0.0.1:8000
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import markdown as md
from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import __version__
from .collector import latest_scores, quota_today
from .config import get_settings
from .db import SessionLocal, init_db
from .models import Collection, Domain, Keyword, Score, Video
from .reports import export_rows, rows_for_domain, write_markdown_report
from .scheduler import collect_all_job, start_background_scheduler
from .youtube import YouTubeClient

TEMPLATES_DIR = Path(__file__).parent / "templates"
REPORTS_DIR = Path("reports")
EXPORTS_DIR = Path("exports")
DAILY_QUOTA = 10_000

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
# Petit verrou pour éviter deux collectes simultanées (SQLite n'aime pas trop)
_collect_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Démarrage : crée les tables et lance le planificateur optionnel."""
    init_db()
    app.state.scheduler = start_background_scheduler()
    yield
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="YT Veille",
    version=__version__,
    description="Veille vidéo par domaine",
    lifespan=lifespan,
)


# ─────────────────────────────────────────────────────────────
#  Dépendances & utilitaires
# ─────────────────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


def _get_domain(session: Session, slug: str) -> Domain:
    domain = session.execute(select(Domain).where(Domain.slug == slug)).scalar_one_or_none()
    if domain is None:
        raise HTTPException(status_code=404, detail=f"Domaine inconnu : {slug}")
    return domain


def _apply_filters(rows: list[dict], min_views: int, order: str) -> list[dict]:
    """Filtre et trie les lignes d'un domaine (côté Python, simple et lisible)."""
    if min_views:
        rows = [r for r in rows if r["view_count"] >= min_views]
    if order == "views":
        rows = sorted(rows, key=lambda r: r["view_count"], reverse=True)
    elif order == "recent":
        rows = sorted(rows, key=lambda r: r["published_at"], reverse=True)
    elif order == "engagement":
        rows = sorted(rows, key=lambda r: r["engagement_pct"], reverse=True)
    else:  # score (déjà trié, mais on garde l'explicite)
        rows = sorted(rows, key=lambda r: r["score_total"], reverse=True)
    return rows


def _recent_collections(session: Session, limit: int = 10):
    return list(
        session.execute(
            select(Collection, Domain)
            .join(Domain, Domain.id == Collection.domain_id)
            .order_by(Collection.started_at.desc())
            .limit(limit)
        )
    )


def _run_collection(slug: str, days: int | None, max_results: int | None) -> None:
    """Collecte exécutée en arrière-plan (threadpool FastAPI)."""
    if not _collect_lock.acquire(blocking=False):
        return  # une collecte est déjà en cours
    settings = get_settings()
    try:
        with SessionLocal() as session:
            domain = session.execute(
                select(Domain).where(Domain.slug == slug)
            ).scalar_one_or_none()
            if domain is None:
                return
            from .collector import collect_domain

            with YouTubeClient(settings.youtube_api_key) as client:
                collect_domain(
                    session, client, domain, freshness_days=days, max_results=max_results
                )
            session.commit()
    finally:
        _collect_lock.release()


# ─────────────────────────────────────────────────────────────
#  Pages HTML
# ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_db)):
    domains = list(session.execute(select(Domain).order_by(Domain.slug)).scalars())
    total_videos = session.execute(select(func.count(Video.id))).scalar() or 0
    usage = quota_today(session)
    pct = round(usage.units_used / DAILY_QUOTA * 100, 1)

    tops = []
    for domain in domains:
        rows = rows_for_domain(session, domain, limit=3)
        tops.append((domain, rows))

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "domains": domains,
            "total_videos": total_videos,
            "usage": usage,
            "quota_pct": pct,
            "tops": tops,
            "collections": _recent_collections(session, limit=8),
        },
    )


@app.get("/domains", response_class=HTMLResponse)
def domains_page(request: Request, session: Session = Depends(get_db)):
    domains = list(session.execute(select(Domain).order_by(Domain.slug)).scalars())
    counts = dict(
        session.execute(
            select(Score.domain_id, func.count(func.distinct(Score.video_pk))).group_by(
                Score.domain_id
            )
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "domains.html",
        {"domains": domains, "counts": counts},
    )


@app.post("/domains")
def create_domain(
    slug: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    session: Session = Depends(get_db),
):
    existing = session.execute(select(Domain).where(Domain.slug == slug)).scalar_one_or_none()
    if existing is None:
        session.add(Domain(slug=slug.strip(), name=name.strip(), description=description.strip()))
        session.commit()
    return RedirectResponse("/domains", status_code=303)


@app.post("/domains/{slug}/keywords")
def add_keyword(
    slug: str, term: str = Form(...), session: Session = Depends(get_db)
):
    domain = _get_domain(session, slug)
    term = term.strip()
    if term and not any(k.term == term for k in domain.keywords):
        session.add(Keyword(domain_id=domain.id, term=term))
        session.commit()
    return RedirectResponse(f"/domains/{slug}", status_code=303)


@app.post("/keywords/{keyword_id}/delete")
def delete_keyword(keyword_id: int, session: Session = Depends(get_db)):
    kw = session.get(Keyword, keyword_id)
    if kw is None:
        raise HTTPException(404, "Mot-clé introuvable")
    slug = kw.domain.slug
    session.delete(kw)
    session.commit()
    return RedirectResponse(f"/domains/{slug}", status_code=303)


@app.post("/domains/{slug}/toggle")
def toggle_domain(slug: str, session: Session = Depends(get_db)):
    domain = _get_domain(session, slug)
    domain.is_active = not domain.is_active
    session.commit()
    return RedirectResponse("/domains", status_code=303)


@app.get("/domains/{slug}", response_class=HTMLResponse)
def domain_detail(
    request: Request,
    slug: str,
    min_views: int = Query(0),
    order: str = Query("score"),
    limit: int = Query(50),
    session: Session = Depends(get_db),
):
    domain = _get_domain(session, slug)
    rows = _apply_filters(rows_for_domain(session, domain), min_views, order)[:limit]
    return templates.TemplateResponse(
        request,
        "domain_detail.html",
        {
            "domain": domain,
            "rows": rows,
            "min_views": min_views,
            "order": order,
            "limit": limit,
            "settings": get_settings(),
        },
    )


@app.post("/domains/{slug}/collect")
def collect_now(
    slug: str,
    background: BackgroundTasks,
    days: int | None = Form(None),
    max_results: int | None = Form(None),
    session: Session = Depends(get_db),
):
    _get_domain(session, slug)  # 404 si inconnu
    background.add_task(_run_collection, slug, days, max_results)
    return RedirectResponse(f"/domains/{slug}?started=1", status_code=303)


@app.get("/videos/{video_id}", response_class=HTMLResponse)
def video_detail(request: Request, video_id: str, session: Session = Depends(get_db)):
    video = session.execute(
        select(Video).where(Video.video_id == video_id)
    ).scalar_one_or_none()
    if video is None:
        raise HTTPException(404, "Vidéo introuvable")
    history = list(
        session.execute(
            select(Score).where(Score.video_pk == video.id).order_by(Score.collected_at.asc())
        ).scalars()
    )
    domain = session.get(Domain, history[0].domain_id) if history else None
    return templates.TemplateResponse(
        request,
        "video.html",
        {"video": video, "history": history, "domain": domain},
    )


@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request, session: Session = Depends(get_db)):
    domains = list(session.execute(select(Domain).order_by(Domain.slug)).scalars())
    available = []
    if REPORTS_DIR.exists():
        for domain in domains:
            folder = REPORTS_DIR / domain.slug
            if folder.exists():
                for f in sorted(folder.glob("*.md"), reverse=True):
                    available.append({"domain": domain, "file": f, "name": f.name})
    return templates.TemplateResponse(
        request, "reports.html", {"reports": available, "domains": domains}
    )


@app.post("/reports/{slug}/generate")
def generate_report(slug: str, session: Session = Depends(get_db)):
    domain = _get_domain(session, slug)
    settings = get_settings()
    write_markdown_report(
        session, domain, REPORTS_DIR, limit=20, freshness_days=settings.freshness_days
    )
    return RedirectResponse("/reports", status_code=303)


@app.get("/reports/{slug}/{name}", response_class=HTMLResponse)
def view_report(request: Request, slug: str, name: str):
    path = REPORTS_DIR / slug / name
    if not path.exists() or path.suffix != ".md":
        raise HTTPException(404, "Rapport introuvable")
    html = md.markdown(path.read_text(encoding="utf-8"), extensions=["tables"])
    return templates.TemplateResponse(
        request, "report_view.html", {"content": html, "slug": slug, "name": name}
    )


@app.get("/domains/{slug}/export")
def download_export(slug: str, fmt: str = Query("csv"), session: Session = Depends(get_db)):
    domain = _get_domain(session, slug)
    rows = rows_for_domain(session, domain)
    if not rows:
        raise HTTPException(404, "Aucune donnée à exporter")
    out = EXPORTS_DIR / f"{domain.slug}.{fmt}"
    path = export_rows(rows, fmt, out)
    return FileResponse(path, filename=f"{domain.slug}.{fmt}")


# ─────────────────────────────────────────────────────────────
#  API JSON
# ─────────────────────────────────────────────────────────────
@app.get("/api/domains")
def api_domains(session: Session = Depends(get_db)):
    domains = session.execute(select(Domain).order_by(Domain.slug)).scalars()
    return [
        {
            "slug": d.slug,
            "name": d.name,
            "is_active": d.is_active,
            "keywords": [k.term for k in d.keywords],
        }
        for d in domains
    ]


@app.get("/api/domains/{slug}/videos")
def api_domain_videos(
    slug: str,
    min_views: int = Query(0),
    order: str = Query("score"),
    limit: int = Query(50),
    session: Session = Depends(get_db),
):
    domain = _get_domain(session, slug)
    rows = _apply_filters(rows_for_domain(session, domain), min_views, order)[:limit]
    return JSONResponse(rows)


@app.get("/api/quota")
def api_quota(session: Session = Depends(get_db)):
    usage = quota_today(session)
    return {
        "day": str(usage.day),
        "units_used": usage.units_used,
        "requests_count": usage.requests_count,
        "daily_limit": DAILY_QUOTA,
    }


# ─────────────────────────────────────────────────────────────
#  Déclenchement externe (cron) — protégé par un jeton secret
# ─────────────────────────────────────────────────────────────
@app.api_route("/api/cron/collect", methods=["GET", "POST"])
def cron_collect(background: BackgroundTasks, token: str = Query("")):
    """Déclenche une collecte de tous les domaines actifs.

    Utilisable par un cron externe (ex. cron-job.org) sur un hébergeur où le
    planificateur interne ne tourne pas. Nécessite `CRON_TOKEN` dans .env.
    """
    settings = get_settings()
    if not settings.cron_token or token != settings.cron_token:
        raise HTTPException(status_code=403, detail="Jeton invalide ou non configuré.")
    background.add_task(collect_all_job)
    return {"status": "started"}
