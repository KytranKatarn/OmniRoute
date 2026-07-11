"""Regression test for the C.R.E.E.D. Gate 1 shift_state bug (found live by the
first autonomous heal cycle, 2026-07-11).

creed_gate_pre_fix read agent['shift_state'] from a query that never SELECTed
that column -> every agent evaluated as shift_state '' -> ALL automated fix
generation was silently denied platform-wide.

The fake cursor returns exactly the columns the SQL text selects, so this test
fails on the broken query and passes only when the SELECT actually fetches
shift_state.
"""

import services.audit_pipeline as ap


class _FakeCursor:
    def __init__(self, shift_state):
        self._shift_state = shift_state
        self._row = None

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if "FROM improvement_proposals" in s:
            self._row = {
                "metadata": {
                    "module_name": "security_network",
                    "file_path": "platform_v2/tools/security_network/routes.py",
                    "issue_code": "WRONG_KWARG",
                    "severity_tier": "red",
                }
            }
        elif "FROM agents" in s:
            row = {"name": "F.O.R.G.E.", "display_name": "F.O.R.G.E.", "department": "Engineering & Technology"}
            # Only expose shift_state when the query actually asks for it —
            # this is what makes the test pin the real defect.
            if "shift_state" in s:
                row["shift_state"] = self._shift_state
            self._row = row
        elif "agent_emotional_state" in s:
            self._row = {"stress_level": 0.2, "energy_level": 0.9}
        else:  # governance_audit_log inserts etc.
            self._row = None

    def fetchone(self):
        return self._row


class _FakeCtx:
    def __init__(self, shift_state):
        self._shift_state = shift_state

    def __enter__(self):
        return (None, _FakeCursor(self._shift_state))

    def __exit__(self, *a):
        return False


def test_active_agent_passes_gate(monkeypatch):
    monkeypatch.setattr(ap, "get_db_cursor", lambda commit=False: _FakeCtx("active"))
    out = ap.creed_gate_pre_fix(123, 42)
    assert out["approved"] is True, f"gate denied an active agent: {out['reason']}"


def test_barracked_agent_still_denied(monkeypatch):
    # the fix must FETCH the column, not weaken the check
    monkeypatch.setattr(ap, "get_db_cursor", lambda commit=False: _FakeCtx("barracked"))
    out = ap.creed_gate_pre_fix(123, 42)
    assert out["approved"] is False
    assert "shift_state" in out["reason"]
