"""The DS9 Codex app-server must be MONITORED, not just displayed (#7384).

The app-server is a host systemd unit (`ds9-codex-appserver.service`) running the
OpenAI Codex CLI's own app-server. Until this existed, NOTHING in the platform
referenced it: the sidecar could die, or lose its login, and the only symptom
would be a coder lane quietly failing hours later.

Three things this test pins down, because each is easy to get wrong:

  1. The platform CANNOT probe the sidecar directly — it listens on the HOST's
     loopback only, and the platform runs in a container, so 127.0.0.1:1456
     there is the container's own. The probe must go through DS9, which is the
     service that actually talks to the sidecar.

  2. A DOWN SIDECAR and an UNREACHABLE DS9 are DIFFERENT conditions, and the
     operator's next action differs. Collapsing them into one "down" would
     send the operator to the wrong place.

  3. A DISABLED connection is a deliberate setting, not a fault. Paging on
     something somebody turned off is how an alert channel gets muted.
"""

from __future__ import annotations

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
def _write_ds9_store(path: Path, *, is_active: int = 1) -> None:
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
    cur.execute(
        "INSERT INTO provider_connections VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "conn-1",
            "codex-app-server",
            "DS9 Codex app-server",
            is_active,
            "apikey",
            "{}",
            None,
            None,
            None,
        ),
    )
    conn.commit()
    conn.close()


def _verdict(valid: bool, code: str | None = None, message: str | None = None):
    def _probe(_cid):
        return {
            "valid": valid,
            "latencyMs": 12,
            "testedAt": "2026-10-21T00:00:00.000Z",
            "diagnosis": {
                "type": "provider_error" if code else "ok",
                "source": "app_server",
                "message": message,
                "code": code,
            },
        }

    return _probe


# ── the classifier ─────────────────────────────────────────────────────────────
def test_a_down_sidecar_is_not_an_unreachable_ds9():
    """DS9 answered; the SIDECAR did not. Those need different actions."""
    c = svc._classify_verdict(
        {
            "valid": False,
            "latencyMs": 10,
            "diagnosis": {
                "type": "provider_error",
                "source": "app_server",
                "message": "Codex app-server unreachable (http://127.0.0.1:1456/readyz: fetch failed)",
                "code": "app_server_unreachable",
            },
        }
    )
    assert c["state"] == "down", c
    assert c["code"] == "app_server_unreachable"
    assert "1456" in c["message"]


def test_an_unreachable_ds9_is_unknown_never_healthy():
    """No verdict at all means DS9 could not be reached: UNKNOWN, not healthy."""
    c = svc._classify_verdict(None)
    assert c["state"] == "unknown", c
    assert c["state"] != "authenticated"


@pytest.mark.parametrize(
    "code,expected",
    [
        ("app_server_unreachable", "down"),
        ("app_server_not_ready", "not_ready"),
        ("app_server_login_required", "signed_out"),
        ("app_server_unconfigured", "not_configured"),
        ("app_server_turn_failed", "turn_failed"),
    ],
)
def test_every_ds9_diagnosis_code_maps_to_a_distinct_state(code, expected):
    """Each of DS9's codes means a DIFFERENT operator action."""
    c = svc._classify_verdict({"valid": False, "diagnosis": {"code": code, "message": "m"}})
    assert c["state"] == expected, c


def test_valid_is_authenticated():
    c = svc._classify_verdict({"valid": True, "diagnosis": {"code": None}})
    assert c["state"] == "authenticated"


# ── the health probe ───────────────────────────────────────────────────────────
def test_healthy_when_the_app_server_answers(tmp_path, monkeypatch):
    db = tmp_path / "storage.sqlite"
    _write_ds9_store(db)
    monkeypatch.setattr(svc, "DS9_DB", str(db))
    monkeypatch.setattr(svc, "_probe", _verdict(True))

    res = svc.get_app_server_health()
    assert res["condition"] == "healthy", res
    assert res["connections"][0]["auth_state"] == "authenticated"
    assert res["checked_at"]


def test_a_dead_sidecar_is_reported_as_down(tmp_path, monkeypatch):
    """The whole point: a dead sidecar must NOT read as healthy."""
    db = tmp_path / "storage.sqlite"
    _write_ds9_store(db)
    monkeypatch.setattr(svc, "DS9_DB", str(db))
    monkeypatch.setattr(
        svc,
        "_probe",
        _verdict(
            False,
            "app_server_unreachable",
            "Codex app-server unreachable (http://127.0.0.1:1456/readyz: fetch failed)",
        ),
    )

    res = svc.get_app_server_health()
    assert res["condition"] == "down", res
    assert "ds9-codex-appserver.service" in res["detail"]
    assert "1456" in res["detail"]


def test_a_disabled_connection_is_not_a_fault(tmp_path, monkeypatch):
    """is_active=0 is somebody's decision. It must never raise an alarm."""
    db = tmp_path / "storage.sqlite"
    _write_ds9_store(db, is_active=0)
    monkeypatch.setattr(svc, "DS9_DB", str(db))
    monkeypatch.setattr(svc, "_probe", _verdict(False, "app_server_unreachable"))

    res = svc.get_app_server_health()
    assert res["condition"] == "disabled", res


def test_no_connection_at_all_is_absent_not_unhealthy(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "DS9_DB", str(tmp_path / "nope.sqlite"))
    res = svc.get_app_server_health()
    assert res["condition"] == "absent", res


def test_the_probe_never_raises_when_ds9_is_unreachable(tmp_path, monkeypatch):
    db = tmp_path / "storage.sqlite"
    _write_ds9_store(db)
    monkeypatch.setattr(svc, "DS9_DB", str(db))
    monkeypatch.setattr(svc, "_probe", lambda _cid: None)

    res = svc.get_app_server_health()
    assert res["condition"] == "unreachable", res
    assert "UNKNOWN" in res["detail"]


def test_the_card_and_the_monitor_agree_on_the_state(tmp_path, monkeypatch):
    """One classifier, so the tab card and the alarm can never disagree."""
    db = tmp_path / "storage.sqlite"
    _write_ds9_store(db)
    monkeypatch.setattr(svc, "DS9_DB", str(db))
    monkeypatch.setattr(svc, "_probe", _verdict(False, "app_server_login_required", "nope"))
    monkeypatch.setattr(svc, "_models", lambda: {"models": [], "variant_count": 0})

    card = svc.get_app_server_status()["connections"][0]["auth_state"]
    monitor = svc.get_app_server_health()["connections"][0]["auth_state"]
    assert card == monitor == "signed_out"


def test_the_probe_does_not_depend_on_the_model_list(tmp_path, monkeypatch):
    """A health probe must not depend on /v1/models — that is a catalogue read."""
    db = tmp_path / "storage.sqlite"
    _write_ds9_store(db)
    monkeypatch.setattr(svc, "DS9_DB", str(db))
    monkeypatch.setattr(svc, "_probe", _verdict(True))

    def _boom():
        raise AssertionError("the health probe must not read the model list")

    monkeypatch.setattr(svc, "_models", _boom)
    assert svc.get_app_server_health()["condition"] == "healthy"
