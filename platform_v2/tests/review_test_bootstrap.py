"""Explicit bootstrap for isolated review tests; never boot Repair Bay routes."""

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("tools.repair_bay")
package.__path__ = [str(ROOT / "tools" / "repair_bay")]
sys.modules.setdefault("tools.repair_bay", package)


@pytest.fixture(autouse=True)
def no_external_review_io(monkeypatch):
    import psycopg2
    import requests
    import urllib.request

    def forbidden(*_args, **_kwargs):
        raise AssertionError("External database/HTTP access forbidden in review tests")

    monkeypatch.setattr(psycopg2, "connect", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
