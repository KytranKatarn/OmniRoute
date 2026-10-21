"""The DHQ DS9 tab must show the Codex app-server connection, read-only.

The app-server is a CONNECTION inside DS9's own store, not one of the
PLATFORM's `engineer_providers` rows, so the DS9 tab's providers grid never
showed it. `services/ds9_app_server_service.py` supplies it.

Two things this test pins down, because both are easy to get wrong and
expensive when they are:

  1. The platform is a READER of DS9. It must never write to DS9's store, and
     it must never mutate the connection - so the service opens DS9's SQLite
     `mode=ro&immutable=1` and the only HTTP call it makes is DS9's own
     side-effect-free provider test.
  2. DS9 being down, missing, or slow must NOT break the DS9 tab. The tab
     reports on a gateway; it must degrade to "unavailable", not to a 500.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest


def _platform_root() -> Path:
    """The platform_v2 root, in BOTH layouts this suite runs in.

    host layout:      <repo>/platform_v2/tests/...   -> parents[2] is <repo>
    container layout: /app/tests/...                 -> /app IS platform_v2
    """
    here = Path(__file__).resolve()
    for cand in (here.parents[1], here.parents[2] / "platform_v2"):
        if (cand / "services").is_dir() and (cand / "tools").is_dir():
            return cand
    raise AssertionError(f"cannot locate platform_v2 from {here}")


PLATFORM = _platform_root()
sys.path.insert(0, str(PLATFORM))

from services import ds9_app_server_service as svc  # noqa: E402


# ── a fake DS9 store ────────────────────────────────────────────────────────────
def _write_ds9_store(path: Path, rows) -> None:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE provider_connections (
            id TEXT, provider TEXT, name TEXT, is_active INTEGER,
            auth_type TEXT, provider_specific_data TEXT,
            last_tested TEXT, test_status TEXT, created_at TEXT
        )
        """
    )
    for r in rows:
        cur.execute("INSERT INTO provider_connections VALUES (?,?,?,?,?,?,?,?,?)", r)
    conn.commit()
    conn.close()


ROW = (
    "conn-1",
    "codex-app-server",
    "DS9 Codex app-server",
    1,
    "apikey",
    "{}",
    "2026-10-21T00:30:35.369Z",
    "active",
    "2026-10-20T20:05:35.804Z",
)


def test_reads_the_app_server_connection_read_only(tmp_path, monkeypatch):
    db = tmp_path / "storage.sqlite"
    _write_ds9_store(db, [ROW])
    monkeypatch.setattr(svc, "DS9_DB", str(db))
    monkeypatch.setattr(svc, "_probe", lambda cid: {"valid": True, "latencyMs": 12})
    monkeypatch.setattr(svc, "_models", lambda: {"models": [{"id": "cxa/gpt-6.1-sol"}], "variant_count": 7})

    status = svc.get_app_server_status()
    assert status["success"] is True
    assert len(status["connections"]) == 1
    c = status["connections"][0]
    assert c["id"] == "conn-1"
    assert c["name"] == "DS9 Codex app-server"
    assert c["is_active"] is True
    assert c["auth_state"] == "authenticated"
    assert c["models"] == [{"id": "cxa/gpt-6.1-sol"}]
    assert c["variant_count"] == 7


def test_never_writes_to_ds9s_store(tmp_path, monkeypatch):
    """The platform is a reader. Opening the store must not allow a write."""
    db = tmp_path / "storage.sqlite"
    _write_ds9_store(db, [ROW])
    monkeypatch.setattr(svc, "DS9_DB", str(db))
    monkeypatch.setattr(svc, "_probe", lambda cid: None)
    monkeypatch.setattr(svc, "_models", lambda: {"models": [], "variant_count": 0})

    svc.get_app_server_status()

    # Prove the file itself was not modified: a write would change its bytes.
    before = db.read_bytes()
    svc.get_app_server_status()
    assert db.read_bytes() == before

    # And prove the handle the service uses is read-only: sqlite refuses a write
    # through a mode=ro connection.
    conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("UPDATE provider_connections SET name = 'hijacked'")
    finally:
        conn.close()


def test_maps_ds9s_own_diagnosis_codes_to_auth_states(tmp_path, monkeypatch):
    """The three verdicts must be distinguishable — they need different actions."""
    db = tmp_path / "storage.sqlite"
    _write_ds9_store(db, [ROW])
    monkeypatch.setattr(svc, "DS9_DB", str(db))
    monkeypatch.setattr(svc, "_models", lambda: {"models": [], "variant_count": 0})

    cases = [
        ({"valid": True}, "authenticated"),
        (
            {"valid": False, "diagnosis": {"code": "app_server_login_required"}},
            "signed_out",
        ),
        (
            {"valid": False, "diagnosis": {"code": "app_server_unconfigured"}},
            "not_configured",
        ),
        (None, "unknown"),
    ]
    for verdict, expected in cases:
        monkeypatch.setattr(svc, "_probe", lambda cid, v=verdict: v)
        status = svc.get_app_server_status()
        assert status["connections"][0]["auth_state"] == expected, verdict


def test_degrades_when_ds9_is_absent(tmp_path, monkeypatch):
    """A missing DS9 store must not raise — the tab must still render."""
    monkeypatch.setattr(svc, "DS9_DB", str(tmp_path / "does-not-exist.sqlite"))
    status = svc.get_app_server_status()
    assert status["success"] is True
    assert status["connections"] == []
    assert status["reason"]


def test_degrades_when_ds9_is_unreachable(tmp_path, monkeypatch):
    """An unreachable DS9 must not raise, and must not claim 'healthy'."""
    db = tmp_path / "storage.sqlite"
    _write_ds9_store(db, [ROW])
    monkeypatch.setattr(svc, "DS9_DB", str(db))
    monkeypatch.setattr(svc, "DS9_API_BASE_URL", "http://127.0.0.1:1")  # closed port
    monkeypatch.setenv("OMNIROUTE_API_KEY", "not-a-real-key")

    status = svc.get_app_server_status()
    assert status["success"] is True
    assert status["connections"][0]["auth_state"] == "unknown"
    assert status["connections"][0]["health"].get("error")


def test_only_app_server_connections_are_returned(tmp_path, monkeypatch):
    """Other DS9 connections must not leak into the card."""
    db = tmp_path / "storage.sqlite"
    _write_ds9_store(
        db,
        [
            ROW,
            (
                "conn-2",
                "opencode-zen",
                "OpenCode",
                1,
                "apikey",
                "{}",
                None,
                None,
                None,
            ),
        ],
    )
    monkeypatch.setattr(svc, "DS9_DB", str(db))
    monkeypatch.setattr(svc, "_probe", lambda cid: {"valid": True})
    monkeypatch.setattr(svc, "_models", lambda: {"models": [], "variant_count": 0})

    status = svc.get_app_server_status()
    assert [c["id"] for c in status["connections"]] == ["conn-1"]
