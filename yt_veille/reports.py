"""Génération des rapports Markdown et des exports (CSV / JSON / Excel)."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from .collector import latest_scores
from .models import Channel, Domain, Score, Video

EXPORT_COLUMNS = [
    "rank",
    "score_total",
    "video_id",
    "title",
    "channel",
    "view_count",
    "like_count",
    "comment_count",
    "engagement_pct",
    "published_at",
    "age_days",
    "duration_seconds",
    "score_views",
    "score_engagement",
    "score_growth",
    "score_relevance",
    "score_recency",
    "url",
]


def _url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _hms(seconds: int) -> str:
    """Durée en « 12:34 » ou « 1:02:03 »."""
    seconds = max(int(seconds or 0), 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _age_days(published_at: datetime, now: datetime) -> float:
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return round((now - published_at).total_seconds() / 86400.0, 2)


def rows_for_domain(session: Session, domain: Domain, limit: int | None = None) -> list[dict]:
    """Construit la liste de lignes (dict) prête à exporter / afficher."""
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    # `latest_scores` renvoie déjà les vidéos triées du meilleur au moins bon :
    # la position dans la liste *est* le rang (fiable même après une purge).
    for position, (score, video, channel) in enumerate(
        latest_scores(session, domain.id), start=1
    ):
        engagement = (
            (video.like_count + 2 * video.comment_count) / video.view_count * 100
            if video.view_count
            else 0.0
        )
        rows.append(
            {
                "rank": position,
                "score_total": round(score.score_total, 4),
                "video_id": video.video_id,
                "title": video.title,
                "channel": channel.title if channel else "",
                "view_count": video.view_count,
                "like_count": video.like_count,
                "comment_count": video.comment_count,
                "engagement_pct": round(engagement, 2),
                "published_at": video.published_at.isoformat(),
                "age_days": _age_days(video.published_at, now),
                "duration_seconds": video.duration_seconds,
                "score_views": round(score.score_views, 4),
                "score_engagement": round(score.score_engagement, 4),
                "score_growth": round(score.score_growth, 4),
                "score_relevance": round(score.score_relevance, 4),
                "score_recency": round(score.score_recency, 4),
                "url": _url(video.video_id),
                # Champs d'affichage (non exportés en CSV)
                "thumbnail_url": video.thumbnail_url,
                "duration_hms": _hms(video.duration_seconds),
                "channel_url": (
                    f"https://www.youtube.com/channel/{video.channel_id}"
                    if video.channel_id
                    else ""
                ),
            }
        )
    if limit:
        rows = rows[:limit]
    return rows


# ─────────────────────────────────────────────────────────────
#  Rapport Markdown
# ─────────────────────────────────────────────────────────────
def build_markdown_report(
    session: Session,
    domain: Domain,
    limit: int = 10,
    freshness_days: int = 7,
) -> str:
    rows = rows_for_domain(session, domain, limit=limit)
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    lines = [
        f"# Veille « {domain.name} » — {today}",
        "",
        f"Fenêtre : {freshness_days} jours · {len(rows)} vidéos affichées · domaine `{domain.slug}`",
        "",
    ]
    if not rows:
        lines.append("_Aucune vidéo collectée pour le moment. Lance une collecte d'abord._")
        return "\n".join(lines) + "\n"

    lines += [
        f"## 🏆 Top {len(rows)}",
        "",
        "| # | Vidéo | Chaîne | Vues | Engagement | Score | Âge (j) |",
        "|---|-------|--------|------|------------|-------|---------|",
    ]
    for r in rows:
        title = r["title"].replace("|", "\\|")
        lines.append(
            f"| {r['rank']} | [{title}]({r['url']}) | {r['channel']} "
            f"| {r['view_count']:,} | {r['engagement_pct']} % "
            f"| {r['score_total']:.3f} | {r['age_days']} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def write_markdown_report(
    session: Session,
    domain: Domain,
    reports_dir: Path,
    limit: int = 10,
    freshness_days: int = 7,
) -> Path:
    content = build_markdown_report(session, domain, limit, freshness_days)
    folder = Path(reports_dir) / domain.slug
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{datetime.now(timezone.utc):%Y-%m-%d}.md"
    path.write_text(content, encoding="utf-8")
    return path


# ─────────────────────────────────────────────────────────────
#  Exports CSV / JSON / Excel
# ─────────────────────────────────────────────────────────────
def _selected(rows: list[dict]) -> list[dict]:
    """Ne garde que les colonnes d'export (ignore les champs d'affichage web)."""
    return [{col: row.get(col) for col in EXPORT_COLUMNS} for row in rows]


def export_csv(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def export_json(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_selected(rows), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def export_xlsx(rows: list[dict], path: Path) -> Path:
    from openpyxl import Workbook  # import paresseux (dépendance optionnelle en pratique)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "videos"
    ws.append(EXPORT_COLUMNS)
    for r in rows:
        ws.append([r.get(col) for col in EXPORT_COLUMNS])
    wb.save(path)
    return path


def export_rows(rows: list[dict], fmt: str, path: Path) -> Path:
    fmt = fmt.lower()
    if fmt == "csv":
        return export_csv(rows, path)
    if fmt == "json":
        return export_json(rows, path)
    if fmt in {"xlsx", "excel"}:
        return export_xlsx(rows, path)
    raise ValueError(f"Format inconnu : {fmt} (attendu : csv, json ou xlsx)")
