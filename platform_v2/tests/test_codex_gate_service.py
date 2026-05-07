"""Tests for codex_gate_service — C.O.D.E.X. auto-documentation gate."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_importable():
    from services.codex_gate_service import document_deploy

    assert callable(document_deploy)


def test_document_deploy_returns_dict():
    from services.codex_gate_service import document_deploy

    r = document_deploy(
        module="test_module",
        git_commit="abc123f",
        changes_summary="test change for unit test",
        proposal_id=None,
    )
    assert isinstance(r, dict)
    assert "success" in r


def test_document_deploy_nonblocking():
    """C.O.D.E.X. gate is always non-blocking — blocks_deploy must be False."""
    from services.codex_gate_service import document_deploy

    r = document_deploy(module="any", git_commit=None, changes_summary="", proposal_id=None)
    assert r.get("blocks_deploy") is not True
