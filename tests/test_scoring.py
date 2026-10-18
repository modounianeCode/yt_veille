"""Tests unitaires du scoring (fonctions pures → faciles à vérifier)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from yt_veille.scoring import (
    Candidate,
    Weights,
    is_relevant,
    normalize,
    raw_engagement,
    raw_growth,
    raw_recency,
    raw_relevance,
    raw_views,
    score_batch,
)

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def test_normalize_min_max():
    assert normalize([0, 5, 10]) == [0.0, 0.5, 1.0]


def test_normalize_all_equal_positive():
    assert normalize([3, 3, 3]) == [1.0, 1.0, 1.0]


def test_normalize_all_zero():
    assert normalize([0, 0]) == [0.0, 0.0]


def test_raw_views_is_logarithmic():
    assert raw_views(0) == 0.0
    assert raw_views(1000) > raw_views(100)


def test_raw_engagement_counts_comments_double():
    # 10 likes + 2*5 commentaires = 20 ; /100 vues = 0.2
    assert raw_engagement(100, 10, 5) == 0.2
    assert raw_engagement(0, 10, 5) == 0.0


def test_raw_growth_from_previous_snapshot():
    published = NOW - timedelta(days=2)
    prev_at = NOW - timedelta(hours=2)
    # +1000 vues en 2 h → 500 vues/h
    g = raw_growth(2000, published, NOW, prev_view_count=1000, prev_collected_at=prev_at)
    assert abs(g - 500.0) < 1e-6


def test_raw_growth_first_collection_uses_age():
    published = NOW - timedelta(hours=10)
    # 1000 vues en 10 h → 100 vues/h
    g = raw_growth(1000, published, NOW)
    assert abs(g - 100.0) < 1e-6


def test_raw_recency_decays():
    fresh = raw_recency(NOW, NOW, tau_days=7)
    old = raw_recency(NOW - timedelta(days=7), NOW, tau_days=7)
    assert fresh == 1.0
    assert abs(old - 0.367879) < 1e-3


def test_raw_relevance_matching_and_weights():
    raw, matched = raw_relevance(
        title="Guide FastAPI",
        description="Un tutoriel python",
        tags=["api", "python"],
        keywords=["FastAPI", "python", "absent"],
    )
    # FastAPI : titre(3) ; python : tags(2) + description(1) = 3 → total 6
    assert raw == 6
    assert set(matched) == {"FastAPI", "python"}


def _cand(vid, views, likes, comments, age_days, title, tags=None):
    return Candidate(
        video_id=vid,
        title=title,
        description="",
        tags=tags or [],
        view_count=views,
        like_count=likes,
        comment_count=comments,
        published_at=NOW - timedelta(days=age_days),
    )


def test_score_batch_ranks_and_weights():
    a = _cand("a", 100_000, 5000, 500, 1, "FastAPI avancé", ["fastapi"])
    b = _cand("b", 1_000, 10, 2, 30, "Vieille vidéo générique")
    c = _cand("c", 50_000, 100, 10, 2, "Autre sujet")

    score_batch([a, b, c], ["FastAPI"], Weights(), now=NOW)

    # La vidéo populaire, récente et pertinente doit dominer
    assert a.rank == 1
    assert a.total > b.total
    # Tous les sous-scores sont bornés entre 0 et 1
    for cand in (a, b, c):
        for v in (
            cand.scores.views,
            cand.scores.engagement,
            cand.scores.growth,
            cand.scores.relevance,
            cand.scores.recency,
        ):
            assert 0.0 <= v <= 1.0


def test_invalid_weights_fall_back_to_defaults():
    w = Weights(views=-1, engagement=0, growth=0, relevance=0, recency=0).validated()
    assert w.views == 0.20


def test_les_poids_par_defaut_somment_a_un():
    w = Weights()
    total = w.views + w.engagement + w.growth + w.relevance + w.recency
    assert total == pytest.approx(1.0)
    # La pertinence est le signal le plus fort (correctif anti hors-sujet)
    assert w.relevance > w.views
    assert w.relevance > w.growth
    assert w.relevance >= 0.30


def test_is_relevant_ecarte_les_videos_hors_sujet():
    keywords = ["islam", "coran"]
    # Aucun mot-clé nulle part → hors-sujet
    assert not is_relevant("Britain is being transformed", "", ["news"], keywords)
    # Présent dans le titre
    assert is_relevant("Lecture du Coran", "", [], keywords)
    # Présent seulement dans les tags
    assert is_relevant("Conférence du soir", "", ["Islam"], keywords)
    # Présent seulement dans la description
    assert is_relevant("Vidéo", "Un cours sur le coran", [], keywords)
    # Sans mot-clé ou mots-clés vides → rien n'est pertinent
    assert not is_relevant("Peu importe", "", [], [])
    assert not is_relevant("Peu importe", "", [], ["   "])
