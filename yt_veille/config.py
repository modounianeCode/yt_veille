"""Configuration de l'application.

Toutes les valeurs viennent du fichier `.env` (ou des variables
d'environnement). Voir `.env.example` pour la liste complète.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Réglages de l'outil, chargés depuis `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Clé YouTube Data API v3
    youtube_api_key: str = ""

    # Connexion base de données (SQLite en local, PostgreSQL/Neon en ligne)
    database_url: str = "sqlite:///./yt_veille.db"

    # Fenêtre de fraîcheur : on ne garde que les vidéos des N derniers jours
    freshness_days: int = 7

    # Nombre de résultats demandés à YouTube par mot-clé (max 50)
    max_results_per_keyword: int = 25

    # Ordre de tri de la recherche YouTube
    search_order: str = "relevance"

    # Exiger qu'au moins un mot-clé du domaine apparaisse dans la vidéo
    # (titre, tags ou description). Évite les résultats hors-sujet.
    require_keyword_match: bool = True

    # Paramètre τ de décroissance de la fraîcheur (en jours)
    recency_tau_days: float = 7.0

    # ── Planification ──────────────────────────────────────────
    # Activer les collectes automatiques (utile en ligne)
    schedule_enabled: bool = False
    # Heures de collecte (format « HH:MM,HH:MM », heure locale de schedule_timezone)
    schedule_times: str = "06:00,18:00"
    schedule_timezone: str = "UTC"
    # Jeton secret pour déclencher une collecte via /api/cron/collect (cron externe)
    cron_token: str = ""


@lru_cache
def get_settings() -> Settings:
    """Renvoie les réglages (mis en cache pour toute la durée du process)."""
    return Settings()
