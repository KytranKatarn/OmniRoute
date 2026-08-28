"""Tests for backup_governance_service — W.A.R.D.E.N.'s clearance logic."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_clearance_result_has_required_fields():
    from services.backup_governance_service import request_deploy_clearance

    r = request_deploy_clearance(module="test_module", severity="critical")
    for field in ("approved", "snapshot_id", "gate_level", "reason", "backup_age_hours", "severity"):
        assert field in r, f"Missing field: {field}"


def test_critical_is_soft_gate():
    from services.backup_governance_service import _load_gate_config

    config = _load_gate_config()
    assert config["critical"]["gate_type"] == "soft"


def test_medium_blocks_stale():
    from services.backup_governance_service import _check_backup_freshness

    r = _check_backup_freshness(age_hours=200.0, severity="medium")
    assert r["approved"] is False
    assert r["gate_level"] == "hard"


def test_medium_passes_fresh():
    from services.backup_governance_service import _check_backup_freshness

    r = _check_backup_freshness(age_hours=1.0, severity="medium")
    assert r["approved"] is True


def test_critical_soft_passes_even_stale():
    from services.backup_governance_service import _check_backup_freshness

    r = _check_backup_freshness(age_hours=200.0, severity="critical")
    assert r["approved"] is True  # soft gate — always approves with warning
    assert r["gate_level"] == "soft"


# ── #2706: verify the automated deploy path is gated ────────────────────────────
class _FakeCur:
    def __init__(self, row):
        self._row = row

    def execute(self, *a, **k):
        return None

    def fetchone(self):
        return self._row

    def close(self):
        return None


class _FakeConn:
    def __init__(self, row):
        self._row = row

    def cursor(self, *a, **k):
        return _FakeCur(self._row)

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


def test_deploy_to_production_blocks_on_denied_clearance(monkeypatch):
    """#2706: the AUTOMATED deploy path (proposal_service.deploy_to_production —
    reached via Telegram deploy_approve + director-approval callbacks) must HARD-block
    when W.A.R.D.E.N. denies backup clearance, exactly like run_proposal() does.
    Before #2706 this path only made a backup and never checked the freshness gate."""
    from services import proposal_service
    import services.backup_governance_service as bg

    # A deployable, medium-priority proposal (medium = hard gate).
    row = {"id": 1, "status": "approved", "priority": "medium", "title": "test proposal"}
    monkeypatch.setattr(proposal_service, "_get_db", lambda: _FakeConn(row))
    # W.A.R.D.E.N. denies (stale backup). deploy_to_production imports this from
    # services.backup_governance_service at call time, so patching it here takes effect.
    monkeypatch.setattr(
        bg,
        "request_deploy_clearance",
        lambda **k: {
            "approved": False,
            "snapshot_id": None,
            "gate_level": "hard",
            "reason": "backup age 200.0h exceeds medium limit of 6h",
            "backup_age_hours": 200.0,
            "severity": "medium",
        },
    )

    result = proposal_service.deploy_to_production(1)
    assert result["success"] is False
    assert "clearance denied" in result["error"].lower()
    assert result["clearance"]["approved"] is False
