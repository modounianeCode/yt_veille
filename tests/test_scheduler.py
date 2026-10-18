"""Tests de la planification et du garde-fou de quota."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from yt_veille.collector import estimate_units, remaining_quota
from yt_veille.models import ApiQuotaUsage, Base, Domain, Keyword
from yt_veille.scheduler import _build_jobs, parse_times


def test_parse_times_valid():
    assert parse_times("06:00,18:30") == [(6, 0), (18, 30)]


def test_parse_times_ignores_invalid():
    # « 25:00 » et « abc » sont rejetés ; « 07:5 » est interprété comme 07h05
    assert parse_times("06:00, ,25:00,abc,07:5") == [(6, 0), (7, 5)]


def test_parse_times_empty():
    assert parse_times("") == []
    assert parse_times(None) == []


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        yield s


def test_estimate_units_counts_searches_plus_details(session):
    domain = Domain(slug="d", name="D")
    session.add(domain)
    session.flush()
    for term in ("a", "b", "c"):
        session.add(Keyword(domain_id=domain.id, term=term))
    session.flush()
    # 3 mots-clés × 100 + 2 (vidéos + chaînes)
    assert estimate_units(domain) == 302


def test_remaining_quota_drops_with_usage(session):
    assert remaining_quota(session) == 10_000
    session.add(ApiQuotaUsage(day=date.today(), units_used=2_500, requests_count=10))
    session.flush()
    assert remaining_quota(session) == 7_500


class _FakeScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, func, trigger):
        self.jobs.append((func, trigger))


def test_build_jobs_registers_one_job_per_time(monkeypatch):
    from types import SimpleNamespace

    from yt_veille import scheduler as sch

    monkeypatch.setattr(
        sch,
        "get_settings",
        lambda: SimpleNamespace(schedule_times="06:00,18:30", schedule_timezone="UTC"),
    )
    fake = _FakeScheduler()
    _build_jobs(fake)
    assert len(fake.jobs) == 2
    assert all(func is sch.collect_all_job for func, _ in fake.jobs)
