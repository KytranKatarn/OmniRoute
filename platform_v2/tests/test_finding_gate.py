"""Unit tests for the auto-verify finding gate (Code Health static tier).

Encodes the session's triage discipline: deterministic tools auto-confirm with
zero LLM cost; judgment findings are adversarially verified through DHQ (stubbed
here); any verify error or exhausted budget fails CLOSED to advisory.
"""

import services.finding_gate as fg


def _find(tool, code, conf="high", capability="code"):
    return {
        "tool": tool,
        "code": code,
        "confidence": conf,
        "file": "/app/services/x.py",
        "line": 1,
        "severity": "red",
        "message": "m",
        "module": "[APP_CORE]",
        "capability": capability,
        "target": "platform",
    }


class _Result:
    def __init__(self, success=True, response=""):
        self.success = success
        self.response = response


def test_deterministic_findings_auto_confirm_without_dispatch():
    def stub_dispatch(**kw):
        raise AssertionError("must not dispatch for deterministic findings")

    res = fg.gate(
        [
            _find("ast_sweep", "WRONG_KWARG"),
            _find("pyflakes", "F821"),
            _find("ruff", "F401"),
        ],
        dispatcher=stub_dispatch,
    )
    assert len(res["confirmed"]) == 3
    assert res["advisory"] == []
    assert all(f["verified_by"] == "deterministic" for f in res["confirmed"])


def test_judgment_finding_confirmed_when_verifier_proves_it():
    seen = {}

    def stub_dispatch(**kw):
        seen.update(kw)
        return _Result(True, "CONFIRMED: send_info takes 2 positional args, 4 given")

    res = fg.gate(
        [_find("bandit", "SECURITY_STATIC", conf="medium", capability="security")],
        dispatcher=stub_dispatch,
    )
    assert len(res["confirmed"]) == 1
    assert res["confirmed"][0]["verified_by"] == "dhq_adversarial"
    assert res["advisory"] == []
    assert seen["capability"] == "security"  # verify routes to the owning agent
    assert seen["module_id"] == "finding_gate"


def test_judgment_finding_advisory_when_verifier_rejects():
    res = fg.gate(
        [_find("bandit", "SECURITY_STATIC", conf="medium")],
        dispatcher=lambda **kw: _Result(True, "FALSE-POSITIVE: parameterized query"),
    )
    assert res["confirmed"] == []
    assert len(res["advisory"]) == 1
    assert res["advisory"][0]["advisory"] is True


def test_verify_error_is_fail_closed_advisory():
    def boom(**kw):
        raise RuntimeError("dispatch down")

    res = fg.gate([_find("mypy", "TYPE_ERROR", conf="medium")], dispatcher=boom)
    assert res["confirmed"] == []
    assert len(res["advisory"]) == 1


def test_unsuccessful_dispatch_is_fail_closed_advisory():
    res = fg.gate(
        [_find("mypy", "TYPE_ERROR", conf="medium")],
        dispatcher=lambda **kw: _Result(False, ""),
    )
    assert res["confirmed"] == []
    assert len(res["advisory"]) == 1


def test_verify_budget_caps_dispatch_volume():
    calls = {"n": 0}

    def stub_dispatch(**kw):
        calls["n"] += 1
        return _Result(True, "CONFIRMED: real")

    findings = [_find("mypy", "TYPE_ERROR", conf="medium") for _ in range(5)]
    res = fg.gate(findings, dispatcher=stub_dispatch, max_verifications=2)
    assert calls["n"] == 2  # budget respected
    assert len(res["confirmed"]) == 2
    assert len(res["advisory"]) == 3
    assert all(f.get("gate_reason") == "verify_budget_exhausted" for f in res["advisory"])
