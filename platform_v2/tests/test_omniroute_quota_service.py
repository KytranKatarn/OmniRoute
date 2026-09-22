"""DS9 Phase 2 (quota awareness) — OmniRoute per-provider throttle status.

Pins scan_quota_status / get_quota_status / check_and_alert against live-shaped
call_logs. The keep-alive exclusion and the status bands are the load-bearing
behavior: without the narrow keep-alive match, hourly internal pings on
opencode-zen would be counted as real calls and the throttle rate would be a
lie; with a BLANKET "0 tokens = refused" rule, genuine throttles (which ARE
0-token rows) would be dropped and the rate would be a second lie.

DB notes: the service imports get_db_cursor INSIDE each function (import-time
safety), so the module never holds the reference — tests patch `database`
itself. OMNIROUTE_DB is bound at IMPORT-time, so tests patch the module
constant directly, never the env var.
"""

from __future__ import annotations

import sqlite3

import pytest


CALL_LOGS_SCHEMA = """
CREATE TABLE call_logs (
    id TEXT, timestamp TEXT, status INTEGER, provider TEXT,
    requested_model TEXT, tokens_in INTEGER, tokens_out INTEGER,
    error_type TEXT
);
"""


class _FakeCursor:
    def __init__(self, fetchone_result=None, fetchall_result=None):
        self.executed = []
        self.fetchone_result = fetchone_result
        self.fetchall_result = fetchall_result

    def execute(self, sql, params=None):
        self.executed.append(sql.strip())
        return self

    def fetchone(self):
        return self.fetchone_result

    def fetchall(self):
        return self.fetchall_result


class _FakeDbConn:
    def __init__(self, cursor=None):
        self.cursor = cursor or _FakeCursor()

    def __enter__(self):
        return self, self.cursor

    def __exit__(self, *args):
        return False


@pytest.fixture
def svc(monkeypatch):
    import database

    import services.omniroute_quota_service as _svc

    monkeypatch.setattr(database, "get_db_cursor", lambda commit=False: _FakeDbConn())
    return _svc


@pytest.fixture
def sqlite_path(svc, tmp_path, monkeypatch):
    path = tmp_path / "storage.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(CALL_LOGS_SCHEMA)
    conn.commit()
    conn.close()
    # OMNIROUTE_DB is a module-level constant (bound at import); env alone is
    # not enough, the constant must be pointed at the fixture file.
    monkeypatch.setattr(svc, "OMNIROUTE_DB", str(path))
    return str(path)


def _insert(path, rows):
    conn = sqlite3.connect(path)
    conn.executemany(
        "INSERT INTO call_logs (id, timestamp, status, provider, requested_model, "
        "tokens_in, tokens_out, error_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_keepalive_row_excluded(sqlite_path, svc):
    _insert(sqlite_path, [("1", "2026-09-19T00:00:00Z", 200, "opencode-zen", None, 0, 0, None)])
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM call_logs WHERE id='1'").fetchone()
    assert svc._is_keepalive_row(row) is True
    conn.close()


def test_real_refusal_not_excluded(sqlite_path, svc):
    _insert(
        sqlite_path,
        [("1", "2026-09-19T00:00:00Z", 429, "opencode-zen", "opencode/big-pickle", 0, 0, "rate_limited")],
    )
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM call_logs WHERE id='1'").fetchone()
    assert svc._is_keepalive_row(row) is False
    conn.close()


def test_status_bands(svc, monkeypatch):
    monkeypatch.setattr(svc, "_get_setting_float", lambda key, default: default)
    assert svc._status_for_rate(None) == "unknown"
    assert svc._status_for_rate(0.0) == "ok"
    assert svc._status_for_rate(0.29) == "ok"
    assert svc._status_for_rate(0.30) == "degraded"
    assert svc._status_for_rate(0.69) == "degraded"
    assert svc._status_for_rate(0.70) == "exhausted"
    assert svc._status_for_rate(1.0) == "exhausted"


def test_scan_quota_status_computes_rate_and_writes_snapshot(sqlite_path, svc):
    from datetime import datetime, timedelta, timezone

    # Live call_logs timestamps are ISO with 'T' and 'Z' — mirror the real shape
    # so the window comparison is exercised as it runs in production, and make
    # them NOW-relative so the fixed 24h scan window actually includes them.
    ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _insert(
        sqlite_path,
        [
            # keep-alive, excluded
            ("k1", ts, 200, "opencode-zen", None, 0, 0, None),
            # 2 real calls: 1 throttled, 1 ok
            ("r1", ts, 429, "opencode-zen", "opencode/big-pickle", 0, 0, "rate_limited"),
            ("r2", ts, 200, "opencode-zen", "opencode/big-pickle", 12, 40, None),
        ],
    )

    result = svc.scan_quota_status(window_hours=24)

    assert result["ok"] is True
    assert len(result["providers"]) == 1
    p = result["providers"][0]
    assert p["provider"] == "opencode-zen"
    assert p["total"] == 2  # keep-alive excluded
    assert p["throttled"] == 1
    assert p["rate"] == pytest.approx(0.5)
    assert p["status"] == "degraded"  # 0.5 >= 0.30 default degraded band


def test_scan_quota_status_missing_db_fails_open(svc, monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "OMNIROUTE_DB", str(tmp_path / "does-not-exist.sqlite"))
    result = svc.scan_quota_status(window_hours=24)
    assert result["ok"] is False
    assert result["providers"] == []


def test_get_quota_status_unknown_provider_returns_unknown(svc, monkeypatch):
    import database

    monkeypatch.setattr(database, "get_db_cursor", lambda commit=False: _FakeDbConn(_FakeCursor(fetchone_result=None)))
    result = svc.get_quota_status(provider="nonexistent")
    assert result["status"] == "unknown"
    assert result["total"] == 0


def test_get_quota_status_shapes_a_real_row(svc, monkeypatch):
    from datetime import datetime, timezone

    import database

    fake_row = {
        "provider": "opencode-zen",
        "window_hours": 24,
        "total_calls": 10,
        "throttled_calls": 4,
        "rate": 0.4,
        "status": "degraded",
        "created_at": datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc),
    }
    monkeypatch.setattr(
        database, "get_db_cursor", lambda commit=False: _FakeDbConn(_FakeCursor(fetchone_result=fake_row))
    )
    result = svc.get_quota_status(provider="opencode-zen")
    assert result["provider"] == "opencode-zen"
    assert result["rate"] == 0.4
    assert result["status"] == "degraded"
    assert result["last_scan_at"] == "2026-09-19T12:00:00+00:00"


def test_check_and_alert_fires_on_confirmed_exhaustion(monkeypatch, svc):
    recent_rows = [{"status": "exhausted", "rate": 0.85}, {"status": "exhausted", "rate": 0.80}]
    prior_row = {"status": "degraded"}

    monkeypatch.setattr(svc, "_get_setting_int", lambda key, default: 2)
    monkeypatch.setattr(svc, "_all_providers_with_snapshots", lambda: ["opencode-zen"])
    monkeypatch.setattr(svc, "_recent_snapshots", lambda provider, limit: recent_rows)
    monkeypatch.setattr(svc, "_snapshot_before", lambda provider, offset: prior_row)

    sent = []
    monkeypatch.setattr(
        "services.telegram_service.send_system",
        lambda title, message="", **kw: sent.append((title, message)) or {"ok": True},
    )

    svc.check_and_alert()

    assert len(sent) == 1
    assert "exhausted" in sent[0][0].lower()
    assert "opencode-zen" in sent[0][0]


def test_check_and_alert_silent_when_not_confirmed(monkeypatch, svc):
    monkeypatch.setattr(svc, "_get_setting_int", lambda key, default: 2)
    monkeypatch.setattr(svc, "_all_providers_with_snapshots", lambda: ["opencode-zen"])
    monkeypatch.setattr(
        svc, "_recent_snapshots", lambda provider, limit: [{"status": "exhausted", "rate": 0.8}, {"status": "ok", "rate": 0.1}]
    )
    monkeypatch.setattr(svc, "_snapshot_before", lambda provider, offset: {"status": "ok"})

    sent = []
    monkeypatch.setattr(
        "services.telegram_service.send_system",
        lambda title, message="", **kw: sent.append((title, message)) or {"ok": True},
    )

    svc.check_and_alert()

    assert sent == []


def test_check_and_alert_fires_recovery_once(monkeypatch, svc):
    monkeypatch.setattr(svc, "_get_setting_int", lambda key, default: 2)
    monkeypatch.setattr(svc, "_all_providers_with_snapshots", lambda: ["opencode-zen"])
    monkeypatch.setattr(
        svc, "_recent_snapshots", lambda provider, limit: [{"status": "ok", "rate": 0.1}, {"status": "degraded", "rate": 0.35}]
    )
    monkeypatch.setattr(svc, "_snapshot_before", lambda provider, offset: {"status": "exhausted"})

    sent = []
    monkeypatch.setattr(
        "services.telegram_service.send_system",
        lambda title, message="", **kw: sent.append((title, message)) or {"ok": True},
    )

    svc.check_and_alert()

    assert len(sent) == 1
    assert "recovered" in sent[0][0].lower()


# ============================================================================
# DS9 PHASE 3 — ROUTING-HINT CONSUMPTION (the gate + rotation picker).
# The configure-without-a-deploy contract: every threshold read is patched, and
# get_quota_status is a patch point so the decision layers are pinned without a
# real snapshot row.
# ============================================================================


def test_upstream_for_model_prefix_mapping(svc):
    assert svc.upstream_for_model("auto/coding:free") == "auto"
    assert svc.upstream_for_model("auto/coding") == "auto"
    assert svc.upstream_for_model("opencode/big-pickle") == "opencode"
    assert svc.upstream_for_model("oc/big-pickle") == "opencode"
    assert svc.upstream_for_model("felo-web/felo-search") == "felo-web"
    assert svc.upstream_for_model(None) is None
    assert svc.upstream_for_model("") is None
    assert svc.upstream_for_model("deepseek/deepseek-chat") is None


def test_gate_upstream_fail_open_on_missing_snapshot(svc, monkeypatch):
    monkeypatch.setattr(svc, "get_quota_status", lambda provider: {"status": "unknown", "rate": None})
    gate = svc.gate_upstream("opencode")
    assert gate["allow"] is True
    assert gate["status"] == "unknown"


def test_gate_upstream_allows_ok_and_degraded_warns(svc, monkeypatch):
    monkeypatch.setattr(svc, "get_quota_status", lambda provider: {"status": "ok", "rate": 0.1})
    gate = svc.gate_upstream("auto")
    assert gate["allow"] is True
    assert gate["status"] == "ok"

    monkeypatch.setattr(svc, "get_quota_status", lambda provider: {"status": "degraded", "rate": 0.55})
    gate = svc.gate_upstream("auto")
    assert gate["allow"] is True  # warn, don't block
    assert gate["status"] == "degraded"
    assert "warn" in gate["reason"]


def test_gate_upstream_blocks_exhausted(svc, monkeypatch):
    monkeypatch.setattr(svc, "get_quota_status", lambda provider: {"status": "exhausted", "rate": 0.85})
    gate = svc.gate_upstream("opencode")
    assert gate["allow"] is False
    assert gate["reason"] and "exhausted" in gate["reason"]


def test_gate_upstream_fails_open_on_quota_read_error(svc, monkeypatch):
    def boom(provider):
        raise RuntimeError("db gone")

    monkeypatch.setattr(svc, "get_quota_status", boom)
    gate = svc.gate_upstream("auto")
    assert gate["allow"] is True
    assert "fail-open" in gate["reason"].lower()


def test_prefer_least_throttled_upstream_picks_headroom(svc, monkeypatch):
    statuses = {
        "auto": {"status": "degraded", "rate": 0.55},
        "opencode": {"status": "ok", "rate": 0.12},
        "felo-web": {"status": "exhausted", "rate": 0.9},
        "unmeasured": {"status": "unknown", "rate": None},
    }
    monkeypatch.setattr(svc, "get_quota_status", lambda p: statuses.get(p, {"status": "unknown", "rate": None}))
    best = svc.prefer_least_throttled_upstream(candidates=["auto", "opencode", "felo-web"])
    assert best == "opencode"


def test_prefer_least_throttled_preserves_prefer_when_allowed(svc, monkeypatch):
    monkeypatch.setattr(
        svc, "get_quota_status", lambda p: {"status": "degraded" if p == "auto" else "ok", "rate": 0.40 if p == "auto" else 0.2}
    )
    best = svc.prefer_least_throttled_upstream(candidates=["auto", "opencode"], prefer="auto")
    assert best == "auto"


def test_prefer_least_throttled_returns_none_when_all_exhausted(svc, monkeypatch):
    monkeypatch.setattr(
        svc, "get_quota_status", lambda p: {"status": "exhausted", "rate": 0.9}
    )
    best = svc.prefer_least_throttled_upstream(candidates=["auto", "opencode", "felo-web"])
    assert best is None


def test_prefer_least_throttled_fails_open_on_unmeasured(svc, monkeypatch):
    monkeypatch.setattr(svc, "get_quota_status", lambda p: {"status": "unknown", "rate": None})
    best = svc.prefer_least_throttled_upstream(candidates=["opencode", "auto"])
    assert best in ("opencode", "auto")  # unmeasured sorts first — never None when candidates remain