"""Unit tests for the autonomous Code Health heal cycle (Tasks A6 + A9).

All seams stubbed — no DB, no dispatch, no network. The cycle must: chain
scan -> DHQ fix dispatch -> static reverify; skip dispatch when nothing was
proposed; NEVER deploy or merge (source-scan guard); and only touch the
engine build handoff when explicitly asked.
"""

import inspect

import services.code_health_autoheal as ah


def _summary(**over):
    base = {
        "target": "platform",
        "confirmed": 2,
        "advisory": 1,
        "proposals_created": 2,
        "skipped_duplicates": 0,
        "coverage": {"tools_run": ["ast_sweep"], "tools_skipped": []},
        "fingerprints": [["department_hq", "jobs.py", "WRONG_KWARG"]],
    }
    base.update(over)
    return base


def test_cycle_scans_dispatches_and_reverifies(monkeypatch):
    calls = {}
    monkeypatch.setattr(ah, "_deep_scan", lambda target: _summary())
    monkeypatch.setattr(
        ah,
        "_dispatch_fixes",
        lambda limit: calls.setdefault("limit", limit) and None or {"dispatched": 2, "failed": 0, "skipped": 0},
    )
    monkeypatch.setattr(ah, "_reverify_static", lambda fingerprints: {"fixed": 1, "still_open": 0})
    res = ah.run_autoheal_cycle(target="platform", max_fixes=5)
    assert calls["limit"] == 5
    assert res["proposals_created"] == 2
    assert res["fix_dispatch"]["dispatched"] == 2
    assert res["static_reverify"]["fixed"] == 1
    assert res["scanned"] == "platform"


def test_cycle_skips_dispatch_when_nothing_proposed(monkeypatch):
    monkeypatch.setattr(ah, "_deep_scan", lambda target: _summary(proposals_created=0, confirmed=0, fingerprints=[]))
    called = {"n": 0}
    monkeypatch.setattr(ah, "_dispatch_fixes", lambda limit: called.__setitem__("n", 1))
    monkeypatch.setattr(ah, "_reverify_static", lambda fingerprints: {"fixed": 0, "still_open": 0})
    res = ah.run_autoheal_cycle()
    assert called["n"] == 0
    assert res["fix_dispatch"] == {"dispatched": 0, "failed": 0, "skipped": 0}


def test_cycle_never_deploys():
    src = inspect.getsource(ah)
    assert "deploy_to_production" not in src
    assert "deploy_via_merge" not in src
    assert "merge_pr" not in src


def test_engine_build_handoff_is_optional_and_default_off(monkeypatch):
    monkeypatch.setattr(ah, "_deep_scan", lambda target: _summary())
    monkeypatch.setattr(ah, "_dispatch_fixes", lambda limit: {"dispatched": 1, "failed": 0, "skipped": 0})
    monkeypatch.setattr(ah, "_reverify_static", lambda fingerprints: {"fixed": 0, "still_open": 0})
    hits = {"n": 0}
    monkeypatch.setattr(ah, "_trigger_engine_build", lambda: hits.__setitem__("n", hits["n"] + 1))

    ah.run_autoheal_cycle()
    assert hits["n"] == 0  # default: no engine handoff

    ah.run_autoheal_cycle(engine_build=True)
    assert hits["n"] == 1


def test_engine_build_failure_is_non_fatal(monkeypatch):
    monkeypatch.setattr(ah, "_deep_scan", lambda target: _summary())
    monkeypatch.setattr(ah, "_dispatch_fixes", lambda limit: {"dispatched": 1, "failed": 0, "skipped": 0})
    monkeypatch.setattr(ah, "_reverify_static", lambda fingerprints: {"fixed": 0, "still_open": 0})

    def boom():
        raise RuntimeError("engine unreachable")

    monkeypatch.setattr(ah, "_trigger_engine_build", boom)
    res = ah.run_autoheal_cycle(engine_build=True)  # must not raise
    assert res["proposals_created"] == 2


def test_reverify_static_verdicts(monkeypatch):
    rows = [
        {"id": 11, "metadata": {"file_path": "platform_v2/tools/department_hq/jobs.py", "issue_code": "WRONG_KWARG"}},
        {"id": 12, "metadata": {"file_path": "[AI_BRIDGE]/agent_loop.py", "issue_code": "ARITY_MISMATCH"}},
    ]
    monkeypatch.setattr(ah, "_load_deployed_static", lambda: rows)
    stamped = {}
    monkeypatch.setattr(ah, "_stamp_reverified", lambda pid, verdict: stamped.__setitem__(pid, verdict))

    # proposal 11's fingerprint is still present in the fresh scan -> still_open;
    # proposal 12's fingerprint is gone -> fixed.
    fingerprints = [["department_hq", "jobs.py", "WRONG_KWARG"]]
    res = ah._reverify_static(fingerprints)

    assert stamped == {11: "still_open", 12: "fixed"}
    assert res == {"fixed": 1, "still_open": 1}
