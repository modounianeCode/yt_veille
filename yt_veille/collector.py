"""Pipeline de collecte : de la recherche YouTube jusqu'à l'enregistrement en base."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    ApiQuotaUsage,
    Channel,
    Collection,
    Domain,
    Score,
    Video,
    VideoDomain,
    now_utc,
)
from .scoring import Candidate, Weights, is_relevant, score_batch
from .youtube import (
    COST_CHANNELS,
    COST_SEARCH,
    COST_VIDEOS,
    DEFAULT_DAILY_QUOTA,
    YouTubeClient,
    default_published_after,
)

_DURATION_RE = re.compile(
    r"P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
)


def parse_duration(iso: str | None) -> int:
    """Convertit une durée ISO 8601 (ex. « PT1H2M3S ») en secondes."""
    if not iso:
        return 0
    match = _DURATION_RE.fullmatch(iso)
    if not match:
        return 0
    parts = {k: int(v) if v else 0 for k, v in match.groupdict().items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def _parse_dt(value: str) -> datetime:
    """Parse une date YouTube (« 2026-10-01T12:00:00Z ») en datetime UTC."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _item_to_candidate(item: dict) -> Candidate:
    """Transforme un item `videos.list` en objet `Candidate`."""
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    details = item.get("contentDetails", {})
    thumbnails = snippet.get("thumbnails", {})
    thumb = (
        thumbnails.get("high")
        or thumbnails.get("medium")
        or thumbnails.get("default")
        or {}
    )
    return Candidate(
        video_id=item["id"],
        title=snippet.get("title", ""),
        description=snippet.get("description", ""),
        tags=snippet.get("tags", []) or [],
        view_count=int(stats.get("viewCount", 0) or 0),
        like_count=int(stats.get("likeCount", 0) or 0),
        comment_count=int(stats.get("commentCount", 0) or 0),
        published_at=_parse_dt(snippet["publishedAt"]),
        channel_id=snippet.get("channelId"),
        channel_title=snippet.get("channelTitle", ""),
        duration_seconds=parse_duration(details.get("duration")),
        thumbnail_url=thumb.get("url", ""),
    )


def _previous_snapshot(session: Session, video_pk: int, domain_id: int) -> Score | None:
    """Dernier score enregistré pour (vidéo, domaine) — sert à la croissance."""
    return session.execute(
        select(Score)
        .where(Score.video_pk == video_pk, Score.domain_id == domain_id)
        .order_by(Score.collected_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _upsert_channel(session: Session, item: dict) -> None:
    cid = item["id"]
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    channel = session.get(Channel, cid)
    if channel is None:
        channel = Channel(id=cid)
        session.add(channel)
    channel.title = snippet.get("title", channel.title or "")
    channel.subscriber_count = int(stats.get("subscriberCount", 0) or 0)
    channel.country = snippet.get("country")
    channel.updated_at = now_utc()


def _upsert_video(session: Session, cand: Candidate) -> Video:
    video = session.execute(
        select(Video).where(Video.video_id == cand.video_id)
    ).scalar_one_or_none()
    if video is None:
        video = Video(video_id=cand.video_id, published_at=cand.published_at)
        session.add(video)
    video.title = cand.title
    video.description = cand.description
    video.tags = cand.tags
    video.channel_id = cand.channel_id
    video.published_at = cand.published_at
    video.duration_seconds = cand.duration_seconds
    video.view_count = cand.view_count
    video.like_count = cand.like_count
    video.comment_count = cand.comment_count
    video.thumbnail_url = cand.thumbnail_url
    video.last_fetched_at = now_utc()
    session.flush()  # pour obtenir video.id
    return video


def _track_quota(session: Session, units: int, requests: int) -> None:
    """Incrémente le compteur de quota du jour (table api_quota_usage)."""
    today = date.today()
    usage = session.get(ApiQuotaUsage, today)
    if usage is None:
        usage = ApiQuotaUsage(day=today, units_used=0, requests_count=0)
        session.add(usage)
    usage.units_used += units
    usage.requests_count += requests


def purge_irrelevant(session: Session, domain: Domain) -> int:
    """Supprime les scores et liens des vidéos sans aucun mot-clé du domaine.

    Permet de nettoyer après coup des collectes faites avant le filtre de
    pertinence. Ne consomme aucune unité de quota YouTube.
    """
    keywords = [k.term for k in domain.keywords]
    if not keywords:
        return 0

    rows = session.execute(
        select(VideoDomain.video_pk, Video.title, Video.description, Video.tags)
        .join(Video, Video.id == VideoDomain.video_pk)
        .where(VideoDomain.domain_id == domain.id)
    ).all()

    removed = 0
    for video_pk, title, description, tags in rows:
        if is_relevant(title, description, tags, keywords):
            continue
        session.execute(
            delete(Score).where(
                Score.domain_id == domain.id, Score.video_pk == video_pk
            )
        )
        link = session.get(VideoDomain, (video_pk, domain.id))
        if link is not None:
            session.delete(link)
        removed += 1
    return removed


def collect_domain(
    session: Session,
    client: YouTubeClient,
    domain: Domain,
    freshness_days: int | None = None,
    max_results: int | None = None,
    order: str | None = None,
    now: datetime | None = None,
) -> Collection:
    """Collecte, score et enregistre les vidéos d'un domaine. Renvoie le journal."""
    settings = get_settings()
    freshness_days = freshness_days or settings.freshness_days
    max_results = max_results or settings.max_results_per_keyword
    order = order or settings.search_order
    now = now or datetime.now(timezone.utc)

    collection = Collection(domain_id=domain.id, started_at=now, status="running")
    session.add(collection)
    session.flush()

    # Garde-fou de quota : on n'entame pas une collecte qu'on ne peut pas finir
    estimated = estimate_units(domain)
    remaining = remaining_quota(session)
    if estimated > remaining:
        collection.status = "skipped"
        collection.error_message = (
            f"Quota insuffisant : {estimated} unités estimées, {remaining} restantes."
        )
        collection.finished_at = now_utc()
        session.flush()
        return collection

    units_before = client.units_used
    requests_before = client.requests_count

    try:
        keywords = [k.term for k in domain.keywords]
        if not keywords:
            raise ValueError(f"Le domaine « {domain.slug} » n'a aucun mot-clé.")

        published_after = default_published_after(freshness_days, now)

        # 1) Recherche : on rassemble les identifiants de vidéos uniques
        video_ids: list[str] = []
        seen: set[str] = set()
        for term in keywords:
            for item in client.search(term, published_after, max_results, order):
                vid = item.get("id", {}).get("videoId")
                if vid and vid not in seen:
                    seen.add(vid)
                    video_ids.append(vid)

        # 2) Détails des vidéos
        video_items = client.videos(video_ids) if video_ids else []

        # 3) Chaînes
        channel_ids = [
            it.get("snippet", {}).get("channelId")
            for it in video_items
            if it.get("snippet", {}).get("channelId")
        ]
        if channel_ids:
            for ch in client.channels(channel_ids):
                _upsert_channel(session, ch)

        # 4) Upsert vidéos + préparation du scoring
        #    On écarte d'emblée les vidéos ne citant aucun mot-clé du domaine :
        #    c'est ce qui évite les clips hors-sujet qui font beaucoup de vues.
        candidates: list[Candidate] = []
        video_by_id: dict[str, Video] = {}
        ignored = 0
        for item in video_items:
            cand = _item_to_candidate(item)
            if settings.require_keyword_match and not is_relevant(
                cand.title, cand.description, cand.tags, keywords
            ):
                ignored += 1
                continue
            video = _upsert_video(session, cand)
            video_by_id[cand.video_id] = video

            prev = _previous_snapshot(session, video.id, domain.id)
            if prev is not None:
                cand.raw["prev_views"] = prev.view_count
                cand.raw["prev_collected_at"] = prev.collected_at
            candidates.append(cand)

        # 5) Scoring (avec les poids propres au domaine)
        weights = Weights(
            views=domain.w_views,
            engagement=domain.w_engagement,
            growth=domain.w_growth,
            relevance=domain.w_relevance,
            recency=domain.w_recency,
        )
        score_batch(candidates, keywords, weights, now=now, tau_days=settings.recency_tau_days)

        # 6) Persistance des scores + liens vidéo↔domaine
        for cand in candidates:
            video = video_by_id[cand.video_id]
            session.add(
                Score(
                    video_pk=video.id,
                    domain_id=domain.id,
                    collected_at=now,
                    view_count=cand.view_count,
                    score_total=cand.total,
                    score_views=cand.scores.views,
                    score_engagement=cand.scores.engagement,
                    score_growth=cand.scores.growth,
                    score_relevance=cand.scores.relevance,
                    score_recency=cand.scores.recency,
                    rank_in_domain=cand.rank,
                )
            )
            link = session.get(VideoDomain, (video.id, domain.id))
            if link is None:
                session.add(
                    VideoDomain(
                        video_pk=video.id,
                        domain_id=domain.id,
                        matched_keywords=cand.matched_keywords,
                        first_seen_at=now,
                    )
                )
            else:
                link.matched_keywords = cand.matched_keywords

        # 7) Nettoyage rétroactif : on retire les vidéos déjà en base devenues
        #    hors-sujet (collectées avant l'activation du filtre).
        if settings.require_keyword_match:
            purge_irrelevant(session, domain)

        collection.status = "ok"
        collection.videos_found = len(candidates)

    except Exception as exc:  # on journalise l'erreur sans casser tout le run
        collection.status = "error"
        collection.error_message = str(exc)

    finally:
        collection.finished_at = now_utc()
        collection.api_units_used = client.units_used - units_before
        _track_quota(
            session,
            units=client.units_used - units_before,
            requests=client.requests_count - requests_before,
        )
        session.flush()

    return collection


def collect_all(
    session: Session,
    client: YouTubeClient,
    domain_slug: str | None = None,
    **kwargs,
) -> list[Collection]:
    """Collecte un domaine précis, ou tous les domaines actifs."""
    query = select(Domain).where(Domain.is_active.is_(True))
    if domain_slug:
        query = select(Domain).where(Domain.slug == domain_slug)
    domains = list(session.execute(query).scalars())

    if not domains:
        raise ValueError(
            "Aucun domaine trouvé. Lance d'abord « yt-veille seed » pour en créer."
        )

    results = []
    for domain in domains:
        results.append(collect_domain(session, client, domain, **kwargs))
    return results


def quota_today(session: Session) -> ApiQuotaUsage:
    usage = session.get(ApiQuotaUsage, date.today())
    if usage is None:
        usage = ApiQuotaUsage(day=date.today(), units_used=0, requests_count=0)
    return usage


def estimate_units(domain: Domain) -> int:
    """Estimation du coût en unités de quota pour collecter un domaine.

    Chaque mot-clé = 1 recherche (100 unités) ; + 2 appels de détail au maximum.
    """
    return len(domain.keywords) * COST_SEARCH + COST_VIDEOS + COST_CHANNELS


def remaining_quota(session: Session) -> int:
    """Unités de quota encore disponibles aujourd'hui."""
    return DEFAULT_DAILY_QUOTA - quota_today(session).units_used


def latest_scores(session: Session, domain_id: int):
    """Renvoie le dernier score de chaque vidéo d'un domaine, du meilleur au moins bon."""
    sub = (
        select(Score.video_pk, func.max(Score.collected_at).label("mx"))
        .where(Score.domain_id == domain_id)
        .group_by(Score.video_pk)
        .subquery()
    )
    return list(
        session.execute(
            select(Score, Video, Channel)
            .join(sub, (Score.video_pk == sub.c.video_pk) & (Score.collected_at == sub.c.mx))
            .join(Video, Video.id == Score.video_pk)
            .outerjoin(Channel, Channel.id == Video.channel_id)
            .where(Score.domain_id == domain_id)
            .order_by(Score.score_total.desc())
        )
    )
