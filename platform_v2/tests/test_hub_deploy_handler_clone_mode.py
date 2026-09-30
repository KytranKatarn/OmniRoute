"""host_monitor.handle_hub_deploy — legacy behaviour unchanged, clone mode opt-in.

`HUB_DEPLOY_ROOT` is empty by default, so merging this changes nothing on the live hub.
Set, the handler fast-forwards THAT clone and restarts the containers with the clone's
compose file, the BRAIN as project directory (state mounts), and HUB_CODE_ROOT exported.

host_monitor.py is loaded by PATH, never `importorskip`: a skipped test on a broken import
is exactly how an unmonitored handler looks monitored.
"""

import importlib.util
from pathlib import Path

import pytest

HM_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "host_monitor.py"


@pytest.fixture(scope="module")
def hm():
    spec = importlib.util.spec_from_file_location("host_monitor_under_test", HM_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def stubbed(hm, monkeypatch):
    calls = {"git": [], "run": []}
    monkeypatch.setattr(hm.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(hm.os.path, "exists", lambda p: True)

    def fake_git(checkout, args, timeout=120):
        calls["git"].append((checkout, args))
        out = "Updating aaa..bbb" if args[:1] == ["merge"] else ""
        return {"returncode": 0, "stdout": out or "abc1234", "stderr": ""}

    def fake_run(cmd, timeout=120, cwd=None, env=None):
        calls["run"].append({"cmd": cmd, "cwd": cwd, "env": env})
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(hm, "_hub_run_git", fake_git)
    monkeypatch.setattr(hm, "run_command_full", fake_run)
    monkeypatch.setattr(hm, "_inflight_review_prs", lambda: [])
    return calls


def test_default_is_the_legacy_brain_checkout(hm, stubbed, monkeypatch):
    monkeypatch.delenv("HUB_DEPLOY_ROOT", raising=False)
    out = hm.handle_hub_deploy({})
    assert out["success"] and out["applied"]
    assert {c for c, _ in stubbed["git"]} == {"/mnt/archie_brain"}
    (run,) = stubbed["run"]
    assert run["cmd"] == ["docker", "compose", "restart", "archie_platform", "archie_scheduler"]
    assert run["cwd"] == "/mnt/archie_brain" and run["env"] is None


def test_clone_mode_fast_forwards_the_clone_and_keeps_state_on_the_brain(hm, stubbed, monkeypatch):
    monkeypatch.setenv("HUB_DEPLOY_ROOT", "/mnt/archie_deploy")
    out = hm.handle_hub_deploy({})
    assert out["success"] and out["applied"]
    assert {c for c, _ in stubbed["git"]} == {"/mnt/archie_deploy"}, "git must never touch the brain in clone mode"
    (run,) = stubbed["run"]
    assert run["cmd"][:6] == [
        "docker",
        "compose",
        "-f",
        "/mnt/archie_deploy/docker-compose.yml",
        "--project-directory",
        "/mnt/archie_brain",
    ]
    assert run["cmd"][-2:] == ["archie_platform", "archie_scheduler"]
    assert run["cwd"] == "/mnt/archie_brain"
    assert run["env"]["HUB_CODE_ROOT"] == "/mnt/archie_deploy"


def test_blank_override_is_treated_as_unset(hm, stubbed, monkeypatch):
    monkeypatch.setenv("HUB_DEPLOY_ROOT", "   ")
    hm.handle_hub_deploy({})
    assert {c for c, _ in stubbed["git"]} == {"/mnt/archie_brain"}


def test_clone_mode_still_defers_the_restart_while_reviews_run(hm, stubbed, monkeypatch):
    monkeypatch.setenv("HUB_DEPLOY_ROOT", "/mnt/archie_deploy")
    monkeypatch.setattr(hm, "_inflight_review_prs", lambda: [3551])
    out = hm.handle_hub_deploy({})
    assert out.get("restart_deferred") and stubbed["run"] == []


def test_a_missing_clone_is_refused_not_silently_redirected(hm, monkeypatch):
    monkeypatch.setenv("HUB_DEPLOY_ROOT", "/mnt/archie_deploy")
    monkeypatch.setattr(hm.os.path, "isdir", lambda p: False)
    out = hm.handle_hub_deploy({})
    assert out["success"] is False and "/mnt/archie_deploy" in out["error"]
