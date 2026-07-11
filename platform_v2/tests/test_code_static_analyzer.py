"""Unit tests for the faithful-runtime static-analysis runner (Code Health tier).

The runner's seam (_run_in_runtime) is mocked here; the live integration test
(test_deep_scan_integration.py) exercises the real runtime. These tests pin:
the local-mode platform registry, the runtime-path -> pipeline-identity
translation that process_audit_findings depends on, partial-coverage error
handling, and per-tool finding normalization.
"""

import types

import services.code_static_analyzer as csa


def _proc(stdout="", returncode=0):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def test_registry_platform_target_is_local_faithful():
    t = csa.RUNTIME_REGISTRY["platform"]
    assert t["mode"] == "local"  # deep-scan code already runs inside the faithful container
    assert t["app_root"] == "/app"
    assert "/mnt/archie_brain/ai_bridge" in t["scan_roots"]


def test_pipeline_identity_translation():
    # tools modules -> (module, file relative to the module dir)
    assert csa.pipeline_identity("/app/tools/department_hq/jobs.py") == ("department_hq", "jobs.py")
    assert csa.pipeline_identity("/app/tools/consciousness/services/x.py") == (
        "consciousness",
        "services/x.py",
    )
    # non-module platform files -> the [APP_CORE] placeholder convention
    assert csa.pipeline_identity("/app/services/telegram_service.py") == (
        "[APP_CORE]",
        "services/telegram_service.py",
    )
    # ai_bridge -> [AI_BRIDGE] placeholder
    assert csa.pipeline_identity("/mnt/archie_brain/ai_bridge/agent_loop.py") == (
        "[AI_BRIDGE]",
        "agent_loop.py",
    )
    # unknown roots are not guessed — the caller keeps them advisory-only
    assert csa.pipeline_identity("/somewhere/else.py") == (None, "/somewhere/else.py")


def test_run_normalizes_pyflakes(monkeypatch):
    def fake_exec(target, argv, extra_env=None):
        if "pyflakes" in argv:
            return _proc("/app/services/x.py:3:1 undefined name 'foo'\n", returncode=1)
        return _proc()

    monkeypatch.setattr(csa, "_run_in_runtime", fake_exec)
    monkeypatch.setattr(csa, "_run_ast_sweeps", lambda target, files: [])
    res = csa.run("platform", files=["/app/services/x.py"])
    pf = [f for f in res["findings"] if f["tool"] == "pyflakes"]
    assert len(pf) == 1
    assert pf[0]["code"] == "F821"
    assert pf[0]["line"] == 3
    assert pf[0]["target"] == "platform"
    assert pf[0]["module"] == "[APP_CORE]"
    assert pf[0]["rel_file"] == "services/x.py"
    assert "pyflakes" in res["coverage"]["tools_run"]


def test_tool_crash_is_skipped_not_fatal(monkeypatch):
    def boom(target, argv, extra_env=None):
        raise RuntimeError("runtime unavailable")

    monkeypatch.setattr(csa, "_run_in_runtime", boom)
    monkeypatch.setattr(csa, "_run_ast_sweeps", lambda target, files: [])
    res = csa.run("platform", files=["/app/services/x.py"])
    assert res["findings"] == []
    assert len(res["coverage"]["tools_skipped"]) >= 1  # partial coverage is explicit
    assert "ast_sweep" in res["coverage"]["tools_run"]  # the stubbed sweep still ran


def test_ast_sweep_findings_are_tagged(monkeypatch):
    monkeypatch.setattr(csa, "_run_in_runtime", lambda t, a, extra_env=None: _proc())
    monkeypatch.setattr(
        csa,
        "_run_ast_sweeps",
        lambda target, files: [
            {
                "code": "WRONG_KWARG",
                "severity": "red",
                "file": "/app/tools/department_hq/jobs.py",
                "line": 2,
                "detail": "send_info() has no parameter 'subject' (line 2)",
                "tool": "ast_sweep",
                "confidence": "high",
            }
        ],
    )
    res = csa.run("platform", files=["/app/tools/department_hq/jobs.py"])
    f = [x for x in res["findings"] if x["tool"] == "ast_sweep"][0]
    assert f["confidence"] == "high"
    assert f["module"] == "department_hq"
    assert f["rel_file"] == "jobs.py"
    assert f["capability"] == "code"


def test_bandit_findings_get_security_capability(monkeypatch):
    import json

    def fake_exec(target, argv, extra_env=None):
        if "bandit" in argv:
            payload = {
                "results": [
                    {
                        "filename": "/app/services/x.py",
                        "line_number": 9,
                        "issue_text": "Possible SQL injection",
                    }
                ]
            }
            return _proc(json.dumps(payload))
        return _proc()

    monkeypatch.setattr(csa, "_run_in_runtime", fake_exec)
    monkeypatch.setattr(csa, "_run_ast_sweeps", lambda target, files: [])
    res = csa.run("platform", files=["/app/services/x.py"])
    b = [f for f in res["findings"] if f["tool"] == "bandit"][0]
    assert b["code"] == "SECURITY_STATIC"
    assert b["capability"] == "security"
    assert b["confidence"] == "medium"


def test_unknown_target_raises():
    import pytest

    with pytest.raises(ValueError):
        csa.run("not-a-target")
