"""Tests des routes web sensibles (sans base de données ni réseau)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

from yt_veille import webapp


def test_cron_rejects_when_not_configured(monkeypatch):
    monkeypatch.setattr(webapp, "get_settings", lambda: SimpleNamespace(cron_token=""))
    with pytest.raises(HTTPException) as exc:
        webapp.cron_collect(BackgroundTasks(), token="peu-importe")
    assert exc.value.status_code == 403


def test_cron_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(webapp, "get_settings", lambda: SimpleNamespace(cron_token="s3cr3t"))
    with pytest.raises(HTTPException) as exc:
        webapp.cron_collect(BackgroundTasks(), token="faux")
    assert exc.value.status_code == 403


def test_cron_accepts_valid_token(monkeypatch):
    monkeypatch.setattr(webapp, "get_settings", lambda: SimpleNamespace(cron_token="s3cr3t"))
    scheduled = {}
    monkeypatch.setattr(webapp, "collect_all_job", lambda: scheduled.setdefault("ran", True))
    background = BackgroundTasks()
    result = webapp.cron_collect(background, token="s3cr3t")
    assert result == {"status": "started"}
    # La tâche de collecte a bien été mise en file
    assert webapp.collect_all_job in [t.func for t in background.tasks]


def test_cron_accepte_le_jeton_via_entete(monkeypatch):
    """L'en-tête évite les soucis d'encodage d'un jeton dans l'URL."""
    monkeypatch.setattr(webapp, "get_settings", lambda: SimpleNamespace(cron_token="ab+/=cd"))
    background = BackgroundTasks()
    result = webapp.cron_collect(background, token="", x_cron_token="ab+/=cd")
    assert result == {"status": "started"}


def test_cron_tolere_les_espaces_parasites(monkeypatch):
    """Un espace ou un retour à la ligne collé par erreur ne doit pas bloquer."""
    monkeypatch.setattr(webapp, "get_settings", lambda: SimpleNamespace(cron_token="s3cr3t\n"))
    background = BackgroundTasks()
    assert webapp.cron_collect(background, token="  s3cr3t  ") == {"status": "started"}


def test_cron_distingue_jeton_absent_et_jeton_faux(monkeypatch):
    """Messages distincts : on sait s'il faut corriger Render ou GitHub."""
    monkeypatch.setattr(webapp, "get_settings", lambda: SimpleNamespace(cron_token=""))
    with pytest.raises(HTTPException) as exc:
        webapp.cron_collect(BackgroundTasks(), token="peu-importe")
    assert exc.value.status_code == 403
    assert "configuré" in exc.value.detail

    monkeypatch.setattr(webapp, "get_settings", lambda: SimpleNamespace(cron_token="s3cr3t"))
    with pytest.raises(HTTPException) as exc:
        webapp.cron_collect(BackgroundTasks(), token="faux")
    assert exc.value.status_code == 403
    assert "invalide" in exc.value.detail
