"""Client minimal pour la YouTube Data API v3.

Gère :
- les 3 endpoints utiles (search / videos / channels) ;
- le comptage des unités de quota consommées ;
- une erreur dédiée quand le quota est dépassé.

Coûts de quota (par appel) :
    search.list   → 100 unités
    videos.list   →   1 unité (jusqu'à 50 vidéos par appel)
    channels.list →   1 unité (jusqu'à 50 chaînes par appel)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

API_BASE = "https://www.googleapis.com/youtube/v3"

COST_SEARCH = 100
COST_VIDEOS = 1
COST_CHANNELS = 1

# Limite gratuite par défaut fixée par Google
DEFAULT_DAILY_QUOTA = 10_000


class QuotaExceeded(RuntimeError):
    """Levée quand YouTube refuse la requête pour quota dépassé."""


def _chunks(items: list, size: int):
    """Découpe une liste en paquets de taille `size` (ex. 50)."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


class YouTubeClient:
    """Petit wrapper synchrone et explicite autour de l'API YouTube."""

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ValueError(
                "Clé API YouTube manquante : renseigne YOUTUBE_API_KEY dans le fichier .env"
            )
        self.api_key = api_key
        self.units_used = 0  # unités consommées pendant la vie de ce client
        self.requests_count = 0
        self._client = httpx.Client(timeout=timeout)

    # ── Méthode interne pour tout appel HTTP ──────────────────
    def _get(self, endpoint: str, params: dict, cost: int) -> dict:
        params = {**params, "key": self.api_key}
        response = self._client.get(f"{API_BASE}/{endpoint}", params=params)
        self.units_used += cost
        self.requests_count += 1

        if response.status_code == 403:
            payload = response.json()
            reasons = {
                e.get("reason")
                for e in payload.get("error", {}).get("errors", [])
            }
            if "quotaExceeded" in reasons or "dailyLimitExceeded" in reasons:
                raise QuotaExceeded(
                    "Quota YouTube quotidien dépassé. Réessaie demain ou réduis le nombre "
                    "de domaines/mots-clés."
                )
            raise RuntimeError(f"YouTube a refusé la requête : {payload}")

        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "YouTubeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── 1. Recherche par mot-clé (100 unités) ─────────────────
    def search(
        self,
        query: str,
        published_after: datetime,
        max_results: int = 25,
        order: str = "relevance",
        region_code: str | None = None,
        relevance_language: str | None = None,
    ) -> list[dict]:
        """Cherche des vidéos pour un mot-clé. Renvoie la liste des `items`."""
        params = {
            "part": "id",
            "q": query,
            "type": "video",
            "maxResults": max(1, min(max_results, 50)),
            "order": order,
            "publishedAfter": _to_rfc3339(published_after),
        }
        if region_code:
            params["regionCode"] = region_code
        if relevance_language:
            params["relevanceLanguage"] = relevance_language

        data = self._get("search", params, COST_SEARCH)
        return data.get("items", [])

    # ── 2. Détails de vidéos (1 unité / 50) ───────────────────
    def videos(self, video_ids: list[str]) -> list[dict]:
        """Renvoie snippet + statistics + contentDetails pour chaque vidéo."""
        results: list[dict] = []
        for batch in _chunks(list(dict.fromkeys(video_ids)), 50):
            data = self._get(
                "videos",
                {
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(batch),
                    "maxResults": 50,
                },
                COST_VIDEOS,
            )
            results.extend(data.get("items", []))
        return results

    # ── 3. Détails de chaînes (1 unité / 50) ──────────────────
    def channels(self, channel_ids: list[str]) -> list[dict]:
        results: list[dict] = []
        for batch in _chunks(list(dict.fromkeys(channel_ids)), 50):
            data = self._get(
                "channels",
                {
                    "part": "snippet,statistics",
                    "id": ",".join(batch),
                    "maxResults": 50,
                },
                COST_CHANNELS,
            )
            results.extend(data.get("items", []))
        return results


def _to_rfc3339(dt: datetime) -> str:
    """Convertit une date en chaîne attendue par YouTube (RFC 3339, UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_published_after(freshness_days: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now - timedelta(days=freshness_days)
