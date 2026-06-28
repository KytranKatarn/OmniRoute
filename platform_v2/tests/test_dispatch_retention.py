"""Unit tests for dispatch retention/prune (#4542).

Covers the SAFETY INVARIANTS of services/dispatch_retention_service:
- allowlist statuses only (never prunes running/pending/queued/etc.)
- correct age window passed through
- batched delete loop terminates + returns the right count
- dry_run touches nothing
- keep_days<=0 and enabled=false are clean no-ops
- platform_settings config merge + fail-safe parsing

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_dispatch_retention.py -v
"""

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import dispatch_retention_service as drs  # noqa: E402


class _Conn:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


class _Cur:
    """Fake cursor. DELETE rowcounts come from ``delete_batches`` (popped in order);
    COUNT(*) returns ``count``; platform_settings SELECT returns ``settings_rows``."""

    def __init__(self, delete_batches=None, count=0, settings_rows=None):
        self._delete_batches = list(delete_batches or [])
        self._count = count
        self._settings_rows = settings_rows
        self.rowcount = 0
        self.executed = []  # (sql, params)
        self._last = ""

    def execute(self, sql, params=None):
        self._last = sql
        self.executed.append((sql, params))
        up = sql.strip().upper()
        if up.startswith("DELETE"):
            self.rowcount = self._delete_batches.pop(0) if self._delete_batches else 0

    def fetchone(self):
        return {"n": self._count}

    def fetchall(self):
        return self._settings_rows or []


# --------------------------------------------------------------------------- #
# prune_table — the core safety logic
# --------------------------------------------------------------------------- #
class TestPruneTableSafety:
    def test_only_terminal_statuses_passed(self):
        cur, conn = _Cur(delete_batches=[0]), _Conn()
        drs.prune_table(
            cur,
            conn,
            table="bridge_jobs",
            age_col="created_at",
            statuses=drs.TERMINAL_BRIDGE,
            keep_days=45,
            batch_size=5000,
        )
        # the DELETE's status param must be EXACTLY the terminal allowlist
        delete_calls = [c for c in cur.executed if c[0].strip().upper().startswith("DELETE")]
        assert delete_calls, "no DELETE issued"
        status_param = delete_calls[0][1][0]
        assert status_param == list(drs.TERMINAL_BRIDGE)
        # non-terminal statuses must NEVER appear
        for forbidden in ("running", "pending", "pending_approval", "interrupted", "queued", "claimed"):
            assert forbidden not in status_param

    def test_age_window_passed_through(self):
        cur, conn = _Cur(delete_batches=[0]), _Conn()
        drs.prune_table(
            cur,
            conn,
            table="dispatch_pending_queue",
            age_col="queued_at",
            statuses=drs.TERMINAL_DPQ,
            keep_days=30,
            batch_size=5000,
        )
        params = [c for c in cur.executed if c[0].strip().upper().startswith("DELETE")][0][1]
        assert params[1] == 30  # keep_days
        assert params[2] == 5000  # batch_size

    def test_batch_loop_terminates_and_counts(self):
        # 3 full batches then a partial → total 5000*3 + 1200
        cur, conn = _Cur(delete_batches=[5000, 5000, 5000, 1200]), _Conn()
        total = drs.prune_table(
            cur,
            conn,
            table="bridge_jobs",
            age_col="created_at",
            statuses=drs.TERMINAL_BRIDGE,
            keep_days=45,
            batch_size=5000,
        )
        assert total == 16200
        assert conn.commits == 4  # one per batch

    def test_zero_first_batch_stops_immediately(self):
        cur, conn = _Cur(delete_batches=[0]), _Conn()
        total = drs.prune_table(
            cur,
            conn,
            table="bridge_jobs",
            age_col="created_at",
            statuses=drs.TERMINAL_BRIDGE,
            keep_days=45,
            batch_size=5000,
        )
        assert total == 0
        deletes = [c for c in cur.executed if c[0].strip().upper().startswith("DELETE")]
        assert len(deletes) == 1  # didn't loop forever

    def test_dry_run_deletes_nothing(self):
        cur, conn = _Cur(count=4242), _Conn()
        n = drs.prune_table(
            cur,
            conn,
            table="bridge_jobs",
            age_col="created_at",
            statuses=drs.TERMINAL_BRIDGE,
            keep_days=45,
            batch_size=5000,
            dry_run=True,
        )
        assert n == 4242
        assert conn.commits == 0
        assert not any(c[0].strip().upper().startswith("DELETE") for c in cur.executed)

    def test_keep_days_zero_is_noop(self):
        cur, conn = _Cur(delete_batches=[9999]), _Conn()
        n = drs.prune_table(
            cur,
            conn,
            table="bridge_jobs",
            age_col="created_at",
            statuses=drs.TERMINAL_BRIDGE,
            keep_days=0,
            batch_size=5000,
        )
        assert n == 0
        assert cur.executed == []  # nothing ran at all


# --------------------------------------------------------------------------- #
# prune_table — age-only mode (append-only logs, statuses=None)
# --------------------------------------------------------------------------- #
class TestAgeOnlyPrune:
    def test_no_status_clause_when_statuses_none(self):
        cur, conn = _Cur(delete_batches=[3]), _Conn()
        total = drs.prune_table(
            cur,
            conn,
            table="autonomy_loop_log",
            age_col="created_at",
            statuses=None,
            keep_days=14,
            batch_size=5000,
        )
        assert total == 3
        delete_calls = [c for c in cur.executed if c[0].strip().upper().startswith("DELETE")]
        sql, params = delete_calls[0]
        assert "status = ANY" not in sql  # age-only: NO status guard
        # params begin with keep_days (no leading status list), then batch_size
        assert params[0] == 14
        assert params[1] == 5000

    def test_age_only_dry_run_counts_only(self):
        cur, conn = _Cur(count=382463), _Conn()
        n = drs.prune_table(
            cur,
            conn,
            table="autonomy_loop_log",
            age_col="created_at",
            statuses=None,
            keep_days=14,
            batch_size=5000,
            dry_run=True,
        )
        assert n == 382463
        assert conn.commits == 0
        count_calls = [c for c in cur.executed if c[0].strip().upper().startswith("SELECT")]
        assert "status = ANY" not in count_calls[0][0]
        assert count_calls[0][1] == (14,)  # only keep_days, no status param

    def test_autonomy_registered_age_only(self):
        spec = drs._TABLES["autonomy_loop_log"]
        assert spec["statuses"] is None
        assert spec["age_col"] == "created_at"
        assert drs.DEFAULTS["autonomy_loop_log_keep_days"] == 14

    def test_governance_audit_registered_age_only_qualified(self):
        # schema-qualified key (dup empty copy in `sandbox`) + quoted keyword col
        spec = drs._TABLES["public.governance_audit_log"]
        assert spec["statuses"] is None
        assert spec["age_col"] == '"timestamp"'
        assert drs.DEFAULTS["governance_audit_log_keep_days"] == 365


# --------------------------------------------------------------------------- #
# _load_config — platform_settings merge
# --------------------------------------------------------------------------- #
class TestLoadConfig:
    def test_defaults_when_no_rows(self):
        cfg = drs._load_config(_Cur(settings_rows=[]))
        assert cfg == drs.DEFAULTS

    def test_override_values(self):
        rows = [
            {"key": "retention:bridge_jobs:keep_days", "value": "90"},
            {"key": "retention:dpq:keep_days", "value": "60"},
            {"key": "retention:batch_size", "value": "1000"},
            {"key": "retention:enabled", "value": "false"},
        ]
        cfg = drs._load_config(_Cur(settings_rows=rows))
        assert cfg["bridge_jobs_keep_days"] == 90
        assert cfg["dpq_keep_days"] == 60
        assert cfg["batch_size"] == 1000
        assert cfg["enabled"] is False

    def test_bad_value_falls_back(self):
        rows = [{"key": "retention:bridge_jobs:keep_days", "value": "not-a-number"}]
        cfg = drs._load_config(_Cur(settings_rows=rows))
        assert cfg["bridge_jobs_keep_days"] == drs.DEFAULTS["bridge_jobs_keep_days"]

    def test_unknown_key_ignored(self):
        rows = [{"key": "retention:bogus", "value": "x"}]
        cfg = drs._load_config(_Cur(settings_rows=rows))
        assert cfg == drs.DEFAULTS

    def test_parse_helpers(self):
        assert drs._parse_int("45", 1) == 45
        assert drs._parse_int(None, 7) == 7
        assert drs._parse_int("", 7) == 7
        assert drs._parse_int("junk", 7) == 7
        assert drs._parse_bool("true", False) is True
        assert drs._parse_bool("off", True) is False
        assert drs._parse_bool(None, True) is True


# --------------------------------------------------------------------------- #
# run_retention — orchestration (patched DB)
# --------------------------------------------------------------------------- #
def _patch_cursor(cur, conn):
    @contextmanager
    def fake_get_db_cursor(commit=False):
        yield conn, cur

    fake_db = mock.MagicMock()
    fake_db.get_db_cursor = fake_get_db_cursor
    return mock.patch.dict(sys.modules, {"database": fake_db})


class TestRunRetention:
    def test_disabled_is_noop(self):
        cur = _Cur(settings_rows=[{"key": "retention:enabled", "value": "false"}])
        conn = _Conn()
        with _patch_cursor(cur, conn):
            res = drs.run_retention()
        assert res["enabled"] is False
        assert res["deleted"] == {}
        assert not any(c[0].strip().upper().startswith("DELETE") for c in cur.executed)

    def test_happy_path_prunes_both_tables(self):
        # enabled (default), both tables delete one partial batch each
        cur = _Cur(delete_batches=[10, 5], settings_rows=[])
        conn = _Conn()
        with _patch_cursor(cur, conn):
            res = drs.run_retention()
        assert res["enabled"] is True
        assert res["deleted"]["bridge_jobs"] == 10
        assert res["deleted"]["dispatch_pending_queue"] == 5
        # last_run upsert was attempted
        assert any("platform_settings" in c[0] and c[0].strip().upper().startswith("INSERT") for c in cur.executed)
