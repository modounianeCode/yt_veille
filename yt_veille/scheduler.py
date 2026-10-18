"""Planification des collectes automatiques (APScheduler).

Deux usages :
- `yt-veille worker`  → processus dédié qui tourne en continu ;
- intégré à l'app web quand `SCHEDULE_ENABLED=true` (démarre avec le serveur).

La configuration se fait via `.env` :
    SCHEDULE_ENABLED=true
    SCHEDULE_TIMES=06:00,18:00
    SCHEDULE_TIMEZONE=UTC
"""

from __future__ import annotations

import logging

from .collector import collect_all, quota_today
from .config import get_settings
from .db import SessionLocal, init_db
from .youtube import YouTubeClient

logger = logging.getLogger("yt_veille.scheduler")


def parse_times(spec: str) -> list[tuple[int, int]]:
    """« 06:00,18:30 » → [(6, 0), (18, 30)]. Ignore les entrées invalides."""
    result: list[tuple[int, int]] = []
    for chunk in (spec or "").split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        hh, mm = chunk.split(":", 1)
        try:
            hour, minute = int(hh), int(mm)
        except ValueError:
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            result.append((hour, minute))
    return result


def collect_all_job() -> None:
    """Tâche planifiée : collecte tous les domaines actifs."""
    settings = get_settings()
    if not settings.youtube_api_key:
        logger.warning("Clé API absente : collecte ignorée.")
        return
    try:
        with SessionLocal() as session:
            with YouTubeClient(settings.youtube_api_key) as client:
                results = collect_all(session, client)
            session.commit()
            usage = quota_today(session)
            for coll in results:
                logger.info(
                    "domaine_id=%s statut=%s vidéos=%s unités=%s",
                    coll.domain_id,
                    coll.status,
                    coll.videos_found,
                    coll.api_units_used,
                )
            logger.info("Quota utilisé aujourd'hui : %s unités", usage.units_used)
    except Exception:  # une erreur planifiée ne doit jamais tuer le processus
        logger.exception("Échec de la collecte planifiée")


def _build_jobs(scheduler) -> None:
    settings = get_settings()
    from apscheduler.triggers.cron import CronTrigger

    times = parse_times(settings.schedule_times) or [(6, 0)]
    for hour, minute in times:
        scheduler.add_job(collect_all_job, CronTrigger(hour=hour, minute=minute))
        logger.info("Collecte planifiée à %02d:%02d (%s)", hour, minute, settings.schedule_timezone)


def start_background_scheduler():
    """Démarre le planificateur en arrière-plan (utilisé par l'app web)."""
    settings = get_settings()
    if not settings.schedule_enabled:
        return None
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone=settings.schedule_timezone)
    _build_jobs(scheduler)
    scheduler.start()
    return scheduler


def run_forever() -> None:
    """Exécute le planificateur au premier plan (mode « worker »)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
    from apscheduler.schedulers.blocking import BlockingScheduler

    settings = get_settings()
    scheduler = BlockingScheduler(timezone=settings.schedule_timezone)
    _build_jobs(scheduler)
    logger.info("Planificateur démarré. Ctrl+C pour arrêter.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Arrêt du planificateur.")
