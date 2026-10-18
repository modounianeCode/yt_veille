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

    # Paramètre τ de décroissance de la fraîcheur (en jours)
    recency_tau_days: float = 7.0


@lru_cache
def get_settings() -> Settings:
    """Renvoie les réglages (mis en cache pour toute la durée du process)."""
    return Settings()
