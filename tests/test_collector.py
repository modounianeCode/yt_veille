"""Test d'intégration du pipeline de collecte avec une API YouTube simulée.

On n'appelle pas YouTube : on remplace `YouTubeClient` par un faux client qui
renvoie des données fixes. Cela permet de vérifier toute la chaîne
recherche → scoring → enregistrement.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from yt_veille.collector import collect_domain, latest_scores, parse_duration
from yt_veille.models import Base, Domain, Keyword, Score

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def _make_video(vid, title, channel_id, views, likes, comments, age_hours, tags=None):
    published = NOW - timedelta(hours=age_hours)
    return {
        "id": vid,
        "snippet": {
            "title": title,
            "description": "description de " + title,
            "tags": tags or [],
            "publishedAt": published.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "channelId": channel_id,
            "channelTitle": "Chaîne " + channel_id,
            "thumbnails": {"high": {"url": f"https://img/{vid}.jpg"}},
        },
        "statistics": {
            "viewCount": str(views),
            "likeCount": str(likes),
            "commentCount": str(comments),
        },
        "contentDetails": {"duration": "PT10M30S"},
    }


class FakeClient:
    """Faux client YouTube compatible avec l'interface attendue par le collecteur."""

    def __init__(self, videos, channels):
        self.units_used = 0
        self.requests_count = 0
        self._videos = videos
        self._channels = channels

    def search(self, query, published_after, max_results=25, order="relevance", **kw):
        self.units_used += 100
        self.requests_count += 1
        needle = query.lower()
        ids = [
            vid
            for vid, v in self._videos.items()
            if needle in v["snippet"]["title"].lower()
        ]
        return [{"id": {"videoId": v}} for v in ids][:max_results]

    def videos(self, ids):
        self.units_used += 1
        self.requests_count += 1
        return [self._videos[v] for v in ids if v in self._videos]

    def channels(self, ids):
        self.units_used += 1
        self.requests_count += 1
        return [self._channels[i] for i in ids if i in self._channels]


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        yield s


def _fake_client():
    videos = {
        "vid-hot": _make_video("vid-hot", "FastAPI édition 2026", "C1", 120_000, 8000, 900, 20, ["fastapi"]),
        "vid-mid": _make_video("vid-mid", "FastAPI pour débutants", "C2", 30_000, 900, 120, 40),
        "vid-cold": _make_video("vid-cold", "FastAPI ancienne vidéo", "C1", 2_000, 50, 5, 300),
        "vid-other": _make_video("vid-other", "Cuisine facile", "C3", 500_000, 9000, 400, 10),
    }
    channels = {
        "C1": {"id": "C1", "snippet": {"title": "Chaîne 1"}, "statistics": {"subscriberCount": "10000"}},
        "C2": {"id": "C2", "snippet": {"title": "Chaîne 2"}, "statistics": {"subscriberCount": "5000"}},
        "C3": {"id": "C3", "snippet": {"title": "Chaîne 3"}, "statistics": {"subscriberCount": "900000"}},
    }
    return FakeClient(videos, channels)


def test_parse_duration():
    assert parse_duration("PT1H2M3S") == 3723
    assert parse_duration("PT10M") == 600
    assert parse_duration(None) == 0


def test_collect_domain_end_to_end(session):
    domain = Domain(slug="dev-web", name="Développement Web")
    session.add(domain)
    session.flush()
    session.add(Keyword(domain_id=domain.id, term="FastAPI"))
    session.flush()

    client = _fake_client()
    collection = collect_domain(session, client, domain, now=NOW)
    session.commit()

    assert collection.status == "ok"
    # Seules les vidéos dont le titre contient « FastAPI » remontent : 3
    assert collection.videos_found == 3
    assert client.units_used == 100 + 1 + 1  # 1 search + 1 videos + 1 channels

    scores = session.query(Score).filter_by(domain_id=domain.id).all()
    assert len(scores) == 3

    ranked = latest_scores(session, domain.id)
    best = ranked[0]
    # La vidéo la plus populaire/récente/pertinente doit être première
    assert best[1].video_id == "vid-hot"


def test_collect_computes_growth_on_second_run(session):
    domain = Domain(slug="dev-web", name="Développement Web")
    session.add(domain)
    session.flush()
    session.add(Keyword(domain_id=domain.id, term="FastAPI"))
    session.flush()

    client = _fake_client()
    collect_domain(session, client, domain, now=NOW)
    session.commit()

    # 2e collecte 2 h plus tard, avec des vues en hausse pour vid-hot
    client._videos["vid-hot"]["statistics"]["viewCount"] = "125000"
    later = NOW + timedelta(hours=2)
    collection2 = collect_domain(session, client, domain, now=later)
    session.commit()

    # La 2e collecte ne doit pas échouer silencieusement (bug de fuseau horaire)
    assert collection2.status == "ok", collection2.error_message

    last = (
        session.query(Score)
        .filter_by(domain_id=domain.id)
        .order_by(Score.collected_at.desc())
        .first()
    )
    assert last.collected_at.replace(tzinfo=timezone.utc) == later
    # On doit avoir au moins deux snapshots par vidéo (donc un vrai calcul de croissance)
    assert session.query(Score).filter_by(domain_id=domain.id).count() == 6
