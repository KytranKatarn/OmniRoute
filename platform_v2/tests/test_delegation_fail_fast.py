"""Unit tests for delegate-worker hardening (#cont-103):
- _capability_is_routable: fail-fast signal for dead capabilities (fail-OPEN on doubt)
- _delegation_max_attempts: owner-tunable retry cap (default 3, fail-safe)
- mark_task_failed: auto-dismiss (cancel) once the cap is hit, else blocked

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_delegation_fail_fast.py -v
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import delegation_service as ds  # noqa: E402


class _Cur:
    """Minimal cursor: routes execute() by SQL fragment, returns canned fetchone()."""

    def __init__(self, count=None, skill_row=None, setting=None, raise_on=None):
        self._count = count
        self._skill_row = skill_row
        self._setting = setting
        self._raise_on = raise_on
        self._last = ""
        self.updates = []

    def execute(self, sql, params=None):
        if self._raise_on and self._raise_on in sql:
            raise RuntimeError("simulated DB failure")
        self._last = sql
        if sql.strip().upper().startswith("UPDATE"):
            self.updates.append((sql, params))

    def fetchone(self):
        s = self._last
        if "platform_settings" in s:
            return {"value": self._setting} if self._setting is not None else None
        if "agent_skills" in s:
            return self._skill_row
        if "COUNT(*)" in s and "work_notes" in s:
            return {"n": self._count}
        return None


class _Ctx:
    def __init__(self, cur):
        self._cur = cur

    def __enter__(self):
        return (None, self._cur)

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, cur, dept_map=None):
    monkeypatch.setattr(ds, "get_db_cursor", lambda *a, **k: _Ctx(cur))
    # Control the local `from ...department_coordinator import CAPABILITY_DEPARTMENT_MAP`
    # so routability is deterministic (default empty map → falls through to agent_skills).
    fake = types.ModuleType("department_coordinator")
    fake.CAPABILITY_DEPARTMENT_MAP = {} if dept_map is None else dept_map
    monkeypatch.setitem(sys.modules, "tools.department_hq.services.department_coordinator", fake)


# ── _capability_is_routable ────────────────────────────────────────────────
def test_known_tool_is_routable(monkeypatch):
    # a known-tool short-circuits before any DB call
    _patch(monkeypatch, _Cur(raise_on="agent_skills"))
    assert ds._capability_is_routable("run_qa_suite") is True


def test_empty_capability_is_routable(monkeypatch):
    _patch(monkeypatch, _Cur())
    assert ds._capability_is_routable("") is True


def test_unknown_capability_with_no_agent_is_not_routable(monkeypatch):
    # not a known-tool, not in the map, no agent holds the skill -> fail-fast
    _patch(monkeypatch, _Cur(skill_row=None))
    assert ds._capability_is_routable("totally_made_up_capability_zzz") is False


def test_unknown_capability_with_skilled_agent_is_routable(monkeypatch):
    _patch(monkeypatch, _Cur(skill_row={"?column?": 1}))
    assert ds._capability_is_routable("totally_made_up_capability_zzz") is True


def test_routable_fails_open_on_db_error(monkeypatch):
    # any error verifying -> assume routable (never wrongly fail a real delegation)
    _patch(monkeypatch, _Cur(raise_on="agent_skills"))
    assert ds._capability_is_routable("totally_made_up_capability_zzz") is True


# ── _delegation_max_attempts ───────────────────────────────────────────────
def test_max_attempts_default(monkeypatch):
    _patch(monkeypatch, _Cur(setting=None))
    assert ds._delegation_max_attempts() == 3


def test_max_attempts_from_settings(monkeypatch):
    _patch(monkeypatch, _Cur(setting="5"))
    assert ds._delegation_max_attempts() == 5


def test_max_attempts_fail_safe_on_error(monkeypatch):
    _patch(monkeypatch, _Cur(raise_on="platform_settings"))
    assert ds._delegation_max_attempts() == 3


# ── mark_task_failed: blocked under cap, cancelled at cap ───────────────────
def test_mark_failed_blocks_under_cap(monkeypatch):
    # prior failures = 1, this is attempt 2, cap 3 -> still 'blocked'
    cur = _Cur(count=1, setting="3")
    _patch(monkeypatch, cur)
    ds.mark_task_failed(123, "boom")
    statuses = [p[0] for p in cur.updates]
    assert any("'blocked'" in s for s in statuses)
    assert not any("'cancelled'" in s for s in statuses)


def test_mark_failed_auto_dismisses_at_cap(monkeypatch):
    # prior failures = 2, this is attempt 3, cap 3 -> 'cancelled' (auto-dismiss)
    cur = _Cur(count=2, setting="3")
    _patch(monkeypatch, cur)
    ds.mark_task_failed(123, "boom")
    statuses = [p[0] for p in cur.updates]
    assert any("'cancelled'" in s for s in statuses)
    assert not any("status = 'blocked'" in s for s in statuses)


def test_mark_failed_cap_zero_never_dismisses(monkeypatch):
    # cap <= 0 disables auto-dismiss even with many prior failures
    cur = _Cur(count=99, setting="0")
    _patch(monkeypatch, cur)
    ds.mark_task_failed(123, "boom")
    statuses = [p[0] for p in cur.updates]
    assert any("'blocked'" in s for s in statuses)
    assert not any("'cancelled'" in s for s in statuses)
