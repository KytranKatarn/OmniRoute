"""Tests for backup_governance_service — W.A.R.D.E.N.'s clearance logic."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest


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
