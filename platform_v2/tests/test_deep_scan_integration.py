"""Live faithful-runtime integration for the static scanner tier (Task A8).

Runs ONLY with RUN_LIVE=1 — executes the real toolchain inside the container.
Pre-merge, the runner's app_root is overridden to the test bundle so the
not-yet-deployed services.code_analysis.run_sweeps module resolves from the
branch under test, while the SCANNED FILES and resolver sys.path roots stay
the real runtime (/app + ai_bridge).
"""

import os

import pytest

import services.code_static_analyzer as csa

pytestmark = pytest.mark.skipif(not os.getenv("RUN_LIVE"), reason="live integration (set RUN_LIVE=1)")


def test_platform_target_scan_is_faithful_and_clean(monkeypatch):
    monkeypatch.setitem(csa.RUNTIME_REGISTRY["platform"], "app_root", os.getcwd())
    res = csa.run("platform", files=["/app/tools/department_hq/jobs.py"])
    assert res["target"] == "platform"
    assert "ast_sweep" in res["coverage"]["tools_run"], res["coverage"]
    # jobs.py was cleaned across PRs #2192-#2199 — the deterministic interface
    # classes must be quiet on it now.
    reds = [
        f
        for f in res["findings"]
        if f["code"]
        in ("WRONG_ROOT_IMPORT", "WRONG_SUBMODULE_IMPORT", "MISSING_SYMBOL", "WRONG_KWARG", "ARITY_MISMATCH")
    ]
    assert reds == [], f"unexpected interface regressions: {reds}"


def test_seeded_session_bug_is_caught(tmp_path, monkeypatch):
    """Reintroduce a REAL 2026-07-11 session bug (PR #2193's nonexistent
    services.telegram_service.store_knowledge import) in a scratch file and
    prove the faithful-runtime sweep flags it."""
    monkeypatch.setitem(csa.RUNTIME_REGISTRY["platform"], "app_root", os.getcwd())
    bad = tmp_path / "seeded_bug.py"
    bad.write_text("from services.telegram_service import store_knowledge\n")
    res = csa.run("platform", files=[str(bad)])
    ast_codes = [f["code"] for f in res["findings"] if f["tool"] == "ast_sweep"]
    assert "MISSING_SYMBOL" in ast_codes, res["findings"]
