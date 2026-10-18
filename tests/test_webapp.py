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
