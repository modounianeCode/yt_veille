"""Modèles de données (tables) — SQLAlchemy 2.0.

On utilise des types compatibles SQLite *et* PostgreSQL :
- `BigInteger` pour les compteurs (vues, likes…) ;
- `JSON` pour les listes (tags, mots-clés trouvés).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now_utc() -> datetime:
    """Horodatage UTC « aware » (le bon réflexe pour comparer des dates)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Classe de base de tous les modèles."""


# ─────────────────────────────────────────────────────────────
#  Domaines & mots-clés
# ─────────────────────────────────────────────────────────────
class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Poids du score, réglables par domaine
    w_views: Mapped[float] = mapped_column(Float, default=0.25)
    w_engagement: Mapped[float] = mapped_column(Float, default=0.25)
    w_growth: Mapped[float] = mapped_column(Float, default=0.25)
    w_relevance: Mapped[float] = mapped_column(Float, default=0.15)
    w_recency: Mapped[float] = mapped_column(Float, default=0.10)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    keywords: Mapped[list["Keyword"]] = relationship(
        back_populates="domain", cascade="all, delete-orphan"
    )


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"))
    term: Mapped[str] = mapped_column(String(200))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    domain: Mapped["Domain"] = relationship(back_populates="keywords")

    __table_args__ = (UniqueConstraint("domain_id", "term", name="uq_keyword_domain_term"),)


# ─────────────────────────────────────────────────────────────
#  Chaînes & vidéos
# ─────────────────────────────────────────────────────────────
class Channel(Base):
    __tablename__ = "channels"

    # On utilise l'identifiant YouTube comme clé primaire
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    subscriber_count: Mapped[int] = mapped_column(BigInteger, default=0)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)

    channel_id: Mapped[str | None] = mapped_column(
        ForeignKey("channels.id"), nullable=True
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)

    # Dernières statistiques connues (rafraîchies à chaque collecte)
    view_count: Mapped[int] = mapped_column(BigInteger, default=0)
    like_count: Mapped[int] = mapped_column(BigInteger, default=0)
    comment_count: Mapped[int] = mapped_column(BigInteger, default=0)
    thumbnail_url: Mapped[str] = mapped_column(Text, default="")

    last_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class VideoDomain(Base):
    """Lien N–N entre une vidéo et un domaine (+ mots-clés qui ont matché)."""

    __tablename__ = "video_domains"

    video_pk: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True
    )
    domain_id: Mapped[int] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), primary_key=True
    )
    matched_keywords: Mapped[list] = mapped_column(JSON, default=list)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


# ─────────────────────────────────────────────────────────────
#  Scores (historique daté → permet de calculer la croissance)
# ─────────────────────────────────────────────────────────────
class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_pk: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    # Instantané du nombre de vues au moment du calcul (sert à la croissance)
    view_count: Mapped[int] = mapped_column(BigInteger, default=0)

    score_total: Mapped[float] = mapped_column(Float, default=0.0)
    score_views: Mapped[float] = mapped_column(Float, default=0.0)
    score_engagement: Mapped[float] = mapped_column(Float, default=0.0)
    score_growth: Mapped[float] = mapped_column(Float, default=0.0)
    score_relevance: Mapped[float] = mapped_column(Float, default=0.0)
    score_recency: Mapped[float] = mapped_column(Float, default=0.0)
    rank_in_domain: Mapped[int] = mapped_column(Integer, default=0)


# ─────────────────────────────────────────────────────────────
#  Journal des collectes & quota API
# ─────────────────────────────────────────────────────────────
class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|ok|error
    api_units_used: Mapped[int] = mapped_column(Integer, default=0)
    videos_found: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApiQuotaUsage(Base):
    """Suivi du quota YouTube (10 000 unités/jour par défaut)."""

    __tablename__ = "api_quota_usage"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    units_used: Mapped[int] = mapped_column(Integer, default=0)
    requests_count: Mapped[int] = mapped_column(Integer, default=0)
