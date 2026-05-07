"""Tests for forge_gate_service — F.O.R.G.E. PR gate logic."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_importable():
    from services.forge_gate_service import request_pr_clearance, _load_gate_config

    assert callable(request_pr_clearance)
    assert callable(_load_gate_config)


def test_gate_config_has_severity_levels():
    from services.forge_gate_service import _load_gate_config

    config = _load_gate_config()
    for severity in ("critical", "high", "medium", "low"):
        assert severity in config
        assert "gate_type" in config[severity]


def test_no_commit_returns_soft_approved():
    """If git_commit is None, fail-open (never block due to git unavailability)."""
    from services.forge_gate_service import request_pr_clearance

    r = request_pr_clearance(git_commit=None, severity="medium")
    assert r["approved"] is True
    assert "no_commit" in r["reason"]


def test_clearance_result_has_required_fields():
    from services.forge_gate_service import request_pr_clearance

    r = request_pr_clearance(git_commit="abc123f", severity="low")
    for field in ("approved", "gate_level", "reason", "severity"):
        assert field in r
