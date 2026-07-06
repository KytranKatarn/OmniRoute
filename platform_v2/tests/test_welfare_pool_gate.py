"""Unit tests for services.welfare_governance_service.pool_over_budget_by_skill
(S6-P1-6 — S.I.G.N.A.L. welfare gate / ADR-002 parity with the WTF backlog gate).

Pure-logic tests via a SQL-routing fake cursor — no live DB. Covers the gate decision
(min pool ratio vs pause ratio), the settings-key parameterization (so WTF and S.I.G.N.A.L.
read DIFFERENT keys from the one shared fn), and the fail-OPEN contract (empty pool /
NULL ratio / bad setting / DB error → never gate).

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_welfare_pool_gate.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform_v2 on path

from services import welfare_governance_service as wgs  # noqa: E402


class _FakeCur:
    """Routes execute() by SQL fragment; fetchone() returns the matching canned row.

    settings: {key: value} for the platform_settings read (missing key → None → default).
    min_ratio / n: the pool aggregate row (MIN(24h tokens / budget), COUNT(*)).
    raise_on: substring that, if present in a SQL, raises (to exercise fail-open).
    """

    def __init__(self, settings=None, min_ratio=None, n=0, raise_on=None):
        self._settings = settings or {}
        self._min_ratio = min_ratio
        self._n = n
        self._raise_on = raise_on
        self._last = None
        self.keys_read = []

    def execute(self, sql, params=None):
        if self._raise_on and self._raise_on in sql:
            raise RuntimeError("simulated DB failure")
        self._last = (sql, params)
        if "platform_settings" in sql and params:
            self.keys_read.append(params[0])

    def fetchone(self):
        sql = self._last[0]
        if "platform_settings" in sql:
            key = self._last[1][0]
            if key in self._settings:
                return {"value": str(self._settings[key])}
            return None  # → fn falls back to its 0.9 default
        return {"min_ratio": self._min_ratio, "n": self._n}


class _FakeCtx:
    def __init__(self, cur):
        self._cur = cur

    def __enter__(self):
        return (None, self._cur)

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, cur):
    monkeypatch.setattr("database.get_db_cursor", lambda *a, **k: _FakeCtx(cur))


def test_gates_when_min_ratio_at_or_above_default_pause(monkeypatch):
    # least-loaded agent at 0.95 of its 24h budget, default pause 0.9 → GATE
    _patch(monkeypatch, _FakeCur(min_ratio=0.95, n=2))
    assert wgs.pool_over_budget_by_skill("social_post_draft", "welfare:signal:pool_pause_ratio") is True


def test_not_gated_when_min_ratio_below_pause(monkeypatch):
    # someone in the pool still has headroom (0.5 < 0.9) → do NOT gate
    _patch(monkeypatch, _FakeCur(min_ratio=0.5, n=3))
    assert wgs.pool_over_budget_by_skill("social_post_draft", "welfare:signal:pool_pause_ratio") is False


def test_fail_open_empty_pool(monkeypatch):
    # n=0 → no skilled active agent → never gate (the n=1 single-agent reality is OK)
    _patch(monkeypatch, _FakeCur(min_ratio=None, n=0))
    assert wgs.pool_over_budget_by_skill("nope") is False


def test_fail_open_null_min_ratio(monkeypatch):
    # pool exists but no budget/usage data (NULL ratio) → never gate
    _patch(monkeypatch, _FakeCur(min_ratio=None, n=2))
    assert wgs.pool_over_budget_by_skill("social_content", "welfare:signal:pool_pause_ratio") is False


def test_custom_pause_ratio_from_settings(monkeypatch):
    # ratio 0.85 with a custom pause 0.8 → GATE (would NOT gate at the 0.9 default)
    _patch(monkeypatch, _FakeCur(settings={"welfare:signal:pool_pause_ratio": "0.8"}, min_ratio=0.85, n=2))
    assert wgs.pool_over_budget_by_skill("social_content", "welfare:signal:pool_pause_ratio") is True


def test_reads_the_given_settings_key(monkeypatch):
    # The one shared fn must read the KEY it is handed (WTF vs S.I.G.N.A.L. isolation).
    cur = _FakeCur(settings={"welfare:signal:pool_pause_ratio": "0.7"}, min_ratio=0.75, n=1)
    _patch(monkeypatch, cur)
    res = wgs.pool_over_budget_by_skill("social_content", "welfare:signal:pool_pause_ratio")
    assert cur.keys_read == ["welfare:signal:pool_pause_ratio"]
    assert res is True  # 0.75 >= 0.7


def test_default_key_is_wtf_backlog(monkeypatch):
    # Default settings_key preserves WTF behaviour for the thin jobs.py wrapper.
    cur = _FakeCur(min_ratio=0.1, n=1)
    _patch(monkeypatch, cur)
    wgs.pool_over_budget_by_skill("fact_check_backlog")
    assert cur.keys_read == ["welfare:backlog:pool_pause_ratio"]


def test_bad_settings_value_falls_back_to_default(monkeypatch):
    # non-numeric setting → default 0.9; min_ratio 0.92 → GATE
    _patch(monkeypatch, _FakeCur(settings={"welfare:signal:pool_pause_ratio": "abc"}, min_ratio=0.92, n=2))
    assert wgs.pool_over_budget_by_skill("social_content", "welfare:signal:pool_pause_ratio") is True


def test_fail_open_on_db_error(monkeypatch):
    # any DB exception → fail OPEN (never gate, never raise)
    _patch(monkeypatch, _FakeCur(min_ratio=0.99, n=5, raise_on="platform_settings"))
    assert wgs.pool_over_budget_by_skill("social_post_draft") is False


# ──────────────────────────────────────────────────────────────────────────
# in_flight_over_cap — queue-depth backpressure gate (#4536)
# ──────────────────────────────────────────────────────────────────────────


class _FakeInFlightCur:
    """Routes execute() by SQL fragment: platform_settings → cap; bridge_jobs → count."""

    def __init__(self, settings=None, count=0, raise_on=None):
        self._settings = settings or {}
        self._count = count
        self._raise_on = raise_on
        self._last = None
        self.keys_read = []
        self.count_params = None  # params passed to the bridge_jobs COUNT query

    def execute(self, sql, params=None):
        if self._raise_on and self._raise_on in sql:
            raise RuntimeError("simulated DB failure")
        self._last = (sql, params)
        if "platform_settings" in sql and params:
            self.keys_read.append(params[0])
        if "bridge_jobs" in sql:
            self.count_params = params

    def fetchone(self):
        sql = self._last[0]
        if "platform_settings" in sql:
            key = self._last[1][0]
            if key in self._settings:
                return {"value": str(self._settings[key])}
            return None  # → fn falls back to its default cap
        return {"n": self._count}


def test_in_flight_gates_at_or_above_default_cap(monkeypatch):
    # 26 in-flight, default cap 25, no setting → GATE
    _patch(monkeypatch, _FakeInFlightCur(count=26))
    assert wgs.in_flight_over_cap("fact_check") is True


def test_in_flight_not_gated_below_cap(monkeypatch):
    _patch(monkeypatch, _FakeInFlightCur(count=10))
    assert wgs.in_flight_over_cap("fact_check") is False


def test_in_flight_custom_cap_from_settings(monkeypatch):
    # cap 5 from settings, 6 in-flight → GATE (would NOT gate at the 25 default)
    _patch(monkeypatch, _FakeInFlightCur(settings={"welfare:backlog:max_inflight": "5"}, count=6))
    assert wgs.in_flight_over_cap("bias_backlog") is True


def test_in_flight_cap_zero_disables_gate(monkeypatch):
    # cap <= 0 disables the gate even with a huge in-flight count
    _patch(monkeypatch, _FakeInFlightCur(settings={"welfare:backlog:max_inflight": "0"}, count=1000))
    assert wgs.in_flight_over_cap("fact_check") is False


def test_in_flight_reads_the_cap_key(monkeypatch):
    cur = _FakeInFlightCur(settings={"welfare:backlog:max_inflight": "25"}, count=1)
    _patch(monkeypatch, cur)
    wgs.in_flight_over_cap("geo_extraction")
    assert cur.keys_read == ["welfare:backlog:max_inflight"]


def test_in_flight_bad_cap_falls_back_to_default(monkeypatch):
    # non-numeric cap → default 25; 30 in-flight → GATE
    _patch(monkeypatch, _FakeInFlightCur(settings={"welfare:backlog:max_inflight": "abc"}, count=30))
    assert wgs.in_flight_over_cap("fact_check") is True


def test_in_flight_fail_open_on_db_error(monkeypatch):
    # any DB exception on the count query → fail OPEN (never gate, never raise)
    _patch(monkeypatch, _FakeInFlightCur(count=999, raise_on="bridge_jobs"))
    assert wgs.in_flight_over_cap("fact_check") is False


# ──────────────────────────────────────────────────────────────────────────
# hub_lane_over_cap — aggregate hub 7B admission gate (RCA KB #278774)
# ──────────────────────────────────────────────────────────────────────────


def test_hub_lane_gates_at_or_above_default_cap(monkeypatch):
    # 8 in-flight across the contended lanes, default cap 8 → GATE
    _patch(monkeypatch, _FakeInFlightCur(count=8))
    assert wgs.hub_lane_over_cap() is True


def test_hub_lane_not_gated_below_cap(monkeypatch):
    _patch(monkeypatch, _FakeInFlightCur(count=5))
    assert wgs.hub_lane_over_cap() is False


def test_hub_lane_custom_cap_from_settings(monkeypatch):
    # cap 3 from settings, 4 in-flight → GATE (would NOT gate at the 8 default)
    _patch(monkeypatch, _FakeInFlightCur(settings={"dispatch:hub_inflight_max": "3"}, count=4))
    assert wgs.hub_lane_over_cap() is True


def test_hub_lane_cap_zero_disables_gate(monkeypatch):
    # cap <= 0 disables even with a huge in-flight count (no-deploy kill switch)
    _patch(monkeypatch, _FakeInFlightCur(settings={"dispatch:hub_inflight_max": "0"}, count=1000))
    assert wgs.hub_lane_over_cap() is False


def test_hub_lane_reads_the_cap_key(monkeypatch):
    # Reads the cap key first, then the configurable-lanes key (both platform_settings).
    cur = _FakeInFlightCur(settings={"dispatch:hub_inflight_max": "8"}, count=1)
    _patch(monkeypatch, cur)
    wgs.hub_lane_over_cap()
    assert cur.keys_read == ["dispatch:hub_inflight_max", "dispatch:hub_contended_lanes"]


def test_hub_lane_bad_cap_falls_back_to_default(monkeypatch):
    # non-numeric cap → default 8; 9 in-flight → GATE
    _patch(monkeypatch, _FakeInFlightCur(settings={"dispatch:hub_inflight_max": "abc"}, count=9))
    assert wgs.hub_lane_over_cap() is True


def test_hub_lane_fail_open_on_db_error(monkeypatch):
    _patch(monkeypatch, _FakeInFlightCur(count=999, raise_on="bridge_jobs"))
    assert wgs.hub_lane_over_cap() is False


def test_hub_contended_lanes_include_the_flooders():
    # the lanes that caused the RCA KB #278774 saturation must be gated
    for lane in ("fact_check", "bias_analysis", "code_review"):
        assert lane in wgs.HUB_CONTENDED_LANES


# ──────────────────────────────────────────────────────────────────────────
# effective_hub_lanes + configurable count (RCA KB #278774 generalization f/u)
# ──────────────────────────────────────────────────────────────────────────


def test_effective_hub_lanes_defaults_when_empty():
    # No/empty setting → exactly the defaults (order-stable).
    assert wgs.effective_hub_lanes(None) == list(wgs.HUB_CONTENDED_LANES)
    assert wgs.effective_hub_lanes("") == list(wgs.HUB_CONTENDED_LANES)
    assert wgs.effective_hub_lanes("   ") == list(wgs.HUB_CONTENDED_LANES)


def test_effective_hub_lanes_is_additive_never_drops_defaults():
    # A configured extra ADDS to the count; defaults are always retained (no foot-gun).
    lanes = wgs.effective_hub_lanes("summarize, research")
    for lane in wgs.HUB_CONTENDED_LANES:
        assert lane in lanes
    assert "summarize" in lanes and "research" in lanes


def test_effective_hub_lanes_strips_and_dedups():
    # whitespace trimmed, empty tokens dropped, dupes (incl. a default) collapsed once
    lanes = wgs.effective_hub_lanes(" fact_check , summarize ,, summarize ")
    assert lanes.count("summarize") == 1
    assert lanes.count("fact_check") == 1


def test_hub_lane_count_uses_defaults_when_no_setting(monkeypatch):
    cur = _FakeInFlightCur(count=8)
    _patch(monkeypatch, cur)
    assert wgs.hub_lane_over_cap() is True
    assert set(cur.count_params[0]) == set(wgs.HUB_CONTENDED_LANES)


def test_hub_lane_count_includes_configured_extra(monkeypatch):
    # a future 7B producer added via the CSV setting is folded into the aggregate count
    cur = _FakeInFlightCur(settings={"dispatch:hub_contended_lanes": "summarize,research"}, count=8)
    _patch(monkeypatch, cur)
    assert wgs.hub_lane_over_cap() is True
    assert "summarize" in cur.count_params[0]
    assert "research" in cur.count_params[0]
    for lane in wgs.HUB_CONTENDED_LANES:  # defaults preserved alongside extras
        assert lane in cur.count_params[0]
