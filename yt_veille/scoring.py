"""Algorithmie de scoring — fonctions pures et testables.

Chaque vidéo reçoit 5 sous-scores normalisés entre 0 et 1, puis un score
pondéré. Toutes les fonctions sont indépendantes de la base de données :
elles prennent des nombres et renvoient des nombres (facile à tester).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone


def as_utc(dt: datetime) -> datetime:
    """Force une date à être « aware » en UTC.

    Indispensable car certaines bases (SQLite) relisent les dates sans fuseau :
    soustraire une date naïve à une date aware lève une TypeError.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ─────────────────────────────────────────────────────────────
#  Normalisation
# ─────────────────────────────────────────────────────────────
def normalize(values: list[float]) -> list[float]:
    """Ramène une liste de valeurs entre 0 et 1 (normalisation min-max).

    Si toutes les valeurs sont égales : on renvoie 1.0 pour celles > 0,
    0.0 sinon (évite une division par zéro).
    """
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [1.0 if v > 0 else 0.0 for v in values]
    return [(v - lo) / (hi - lo) for v in values]


# ─────────────────────────────────────────────────────────────
#  Signaux bruts
# ─────────────────────────────────────────────────────────────
def raw_views(view_count: int) -> float:
    """Échelle logarithmique : 10 vues et 10 000 vues ne sont pas si éloignées."""
    return math.log10(max(view_count, 0) + 1)


def raw_engagement(view_count: int, like_count: int, comment_count: int) -> float:
    """Taux d'engagement : les commentaires comptent double (signal plus fort)."""
    if view_count <= 0:
        return 0.0
    return (like_count + 2 * comment_count) / view_count


def raw_growth(
    view_count: int,
    published_at: datetime,
    now: datetime,
    prev_view_count: int | None = None,
    prev_collected_at: datetime | None = None,
) -> float:
    """Vitesse de croissance, en vues par heure.

    - Si on a une collecte précédente : (vues_now − vues_prev) / heures écoulées.
    - Sinon (première collecte) : vues / heures depuis la publication.
    """
    now = as_utc(now)
    published_at = as_utc(published_at)
    if prev_view_count is not None and prev_collected_at is not None:
        hours = max((now - as_utc(prev_collected_at)).total_seconds() / 3600.0, 1e-6)
        return max(view_count - prev_view_count, 0) / hours
    age_hours = max((now - published_at).total_seconds() / 3600.0, 1.0)
    return view_count / age_hours


def raw_relevance(
    title: str, description: str, tags: list[str], keywords: list[str]
) -> tuple[float, list[str]]:
    """Pertinence par rapport aux mots-clés du domaine.

    Barème : présent dans le titre = 3, dans les tags = 2, dans la description = 1.
    Renvoie (score brut, liste des mots-clés qui ont matché).
    """
    title_l = (title or "").lower()
    desc_l = (description or "").lower()
    tags_l = [t.lower() for t in (tags or [])]

    total = 0.0
    matched: list[str] = []
    for kw in keywords:
        k = kw.lower().strip()
        if not k:
            continue
        score = 0
        if k in title_l:
            score += 3
        if any(k in t for t in tags_l):
            score += 2
        if k in desc_l:
            score += 1
        if score:
            matched.append(kw)
            total += score
    return total, matched


def raw_recency(published_at: datetime, now: datetime, tau_days: float = 7.0) -> float:
    """Fraîcheur : décroissance exponentielle exp(−âge_jours / τ)."""
    age_days = max((as_utc(now) - as_utc(published_at)).total_seconds() / 86400.0, 0.0)
    return math.exp(-age_days / max(tau_days, 1e-6))


# ─────────────────────────────────────────────────────────────
#  Combinaison pondérée
# ─────────────────────────────────────────────────────────────
@dataclass
class Weights:
    views: float = 0.25
    engagement: float = 0.25
    growth: float = 0.25
    relevance: float = 0.15
    recency: float = 0.10

    def validated(self) -> "Weights":
        """Empêche des poids invalides (négatifs ou tous nuls)."""
        vals = [self.views, self.engagement, self.growth, self.relevance, self.recency]
        if any(v < 0 for v in vals) or sum(vals) <= 0:
            return Weights()
        return self


@dataclass
class SubScores:
    views: float = 0.0
    engagement: float = 0.0
    growth: float = 0.0
    relevance: float = 0.0
    recency: float = 0.0

    def total(self, weights: Weights) -> float:
        return (
            weights.views * self.views
            + weights.engagement * self.engagement
            + weights.growth * self.growth
            + weights.relevance * self.relevance
            + weights.recency * self.recency
        )


@dataclass
class Candidate:
    """Vidéo candidate en cours de scoring (avant insertion en base)."""

    video_id: str
    title: str
    description: str
    tags: list[str]
    view_count: int
    like_count: int
    comment_count: int
    published_at: datetime
    channel_id: str | None = None
    channel_title: str = ""
    duration_seconds: int = 0
    thumbnail_url: str = ""

    # Remplis pendant le calcul
    matched_keywords: list[str] = field(default_factory=list)
    raw: dict[str, float] = field(default_factory=dict)
    scores: SubScores = field(default_factory=SubScores)
    total: float = 0.0
    rank: int = 0


def score_batch(
    candidates: list[Candidate],
    keywords: list[str],
    weights: Weights,
    now: datetime | None = None,
    tau_days: float = 7.0,
) -> list[Candidate]:
    """Calcule les sous-scores de tout un lot et remplit `total` + `rank`.

    On normalise *par lot* (sur l'ensemble du domaine) : c'est ce qui rend les
    scores comparables entre vidéos d'un même domaine.
    """
    now = now or datetime.now(timezone.utc)
    weights = weights.validated()
    if not candidates:
        return candidates

    raw_views_l, raw_eng_l, raw_growth_l, raw_rel_l, raw_rec_l = [], [], [], [], []

    for c in candidates:
        rel_raw, matched = raw_relevance(c.title, c.description, c.tags, keywords)
        c.matched_keywords = matched

        growth_raw = raw_growth(
            c.view_count,
            c.published_at,
            now,
            prev_view_count=c.raw.get("prev_views"),
            prev_collected_at=c.raw.get("prev_collected_at"),
        )

        c.raw["views"] = raw_views(c.view_count)
        c.raw["engagement"] = raw_engagement(c.view_count, c.like_count, c.comment_count)
        c.raw["growth"] = growth_raw
        c.raw["relevance"] = rel_raw
        c.raw["recency"] = raw_recency(c.published_at, now, tau_days)

        raw_views_l.append(c.raw["views"])
        raw_eng_l.append(c.raw["engagement"])
        raw_growth_l.append(c.raw["growth"])
        raw_rel_l.append(c.raw["relevance"])
        raw_rec_l.append(c.raw["recency"])

    n_views = normalize(raw_views_l)
    n_eng = normalize(raw_eng_l)
    n_growth = normalize(raw_growth_l)
    n_rel = normalize(raw_rel_l)
    n_rec = normalize(raw_rec_l)

    for i, c in enumerate(candidates):
        c.scores = SubScores(
            views=n_views[i],
            engagement=n_eng[i],
            growth=n_growth[i],
            relevance=n_rel[i],
            recency=n_rec[i],
        )
        c.total = round(c.scores.total(weights), 6)

    # Classement (1 = meilleur)
    ordered = sorted(candidates, key=lambda x: x.total, reverse=True)
    for rank, c in enumerate(ordered, start=1):
        c.rank = rank
    return candidates
