"""Opt-in pytest guard for the Atlas/navigation validation command."""

import pytest


@pytest.fixture(autouse=True)
def isolated_application_io(monkeypatch, tmp_path):
    from sqlalchemy.engine import Engine
    import requests
    from consumer import db

    def forbidden(*_args, **_kwargs):
        raise AssertionError("External database/HTTP access is forbidden in Atlas validation")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(db, "_DB_PATH", str(tmp_path / "billing.db"))
