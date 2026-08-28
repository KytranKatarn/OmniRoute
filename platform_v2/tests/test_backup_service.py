"""Tests for backup_service — importable without Flask context."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_importable_without_flask():
    from services.backup_service import get_health_summary, verify_integrity, run_retention, snapshot_module

    assert all(callable(f) for f in [get_health_summary, verify_integrity, run_retention, snapshot_module])


def test_get_health_summary_structure():
    from services.backup_service import get_health_summary

    r = get_health_summary()
    assert isinstance(r, dict)
    assert "status" in r  # "healthy" | "degraded"
    assert "last_backup" in r  # ISO string or None
    assert "tier_health" in r  # dict keyed by tier name


def test_verify_integrity_missing_id():
    from services.backup_service import verify_integrity

    r = verify_integrity(backup_id=999999999)
    assert r["success"] is False
    assert r.get("error") == "not_found"


def test_run_retention_returns_dict():
    from services.backup_service import run_retention

    r = run_retention({"max_age_days": 365, "min_keep": 100})  # safe policy — won't delete anything
    assert isinstance(r, dict)
    assert "success" in r
    assert "pruned" in r
