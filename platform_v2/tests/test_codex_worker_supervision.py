"""No live containers/services: exercise barrier ordering and cleanup boundaries."""

import importlib.util
import json
import os
from pathlib import Path
import socket
import uuid
from unittest.mock import Mock

import pytest


@pytest.fixture
def supervisor():
    path = Path(__file__).resolve().parents[1] / "services/codex_worker_supervision.py"
    spec = importlib.util.spec_from_file_location("isolated_supervisor", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_container_identity_requires_all_labels(supervisor, monkeypatch):
    attempt = str(uuid.uuid4())
    cid = "a" * 64
    data = {
        "id": cid,
        "restart": "no",
        "running": False,
        "restarting": False,
        "labels": {
            "codex.attempt.id": attempt,
            "codex.task.id": "41",
            "codex.host.id": socket.gethostname(),
            "codex.host.boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        },
    }
    command = Mock(side_effect=lambda args: json.dumps(data))
    monkeypatch.setattr(supervisor, "supervisor_command", command)
    assert supervisor.owned_container(cid, 41, attempt)["id"] == cid
    for key in list(data["labels"]):
        original = data["labels"][key]
        data["labels"][key] = "foreign"
        with pytest.raises(ValueError):
            supervisor.owned_container(cid, 41, attempt)
        data["labels"][key] = original
    data["restart"] = "always"
    with pytest.raises(ValueError):
        supervisor.owned_container(cid, 41, attempt)
    command.reset_mock()
    with pytest.raises(ValueError):
        supervisor.owned_container("archie-codex-name", 41, attempt)
    command.assert_not_called()


@pytest.fixture
def simulation(supervisor, monkeypatch, tmp_path):
    os.chmod(tmp_path, 0o700)
    task = {"id": 41, "attempt_id": str(uuid.uuid4())}
    directory = tmp_path / ("codex-attempt-" + task["attempt_id"])
    real_path = Path
    monkeypatch.setattr(
        supervisor,
        "Path",
        lambda p: tmp_path if str(p).startswith("/run/user/") else real_path(p),
    )
    commands = []
    observations = []
    cid = "a" * 64

    def command(args, timeout=30):
        commands.append(args)
        if args[0] == "systemd-run":
            (directory / "container.cid").write_text(cid)
            (directory / "runner.log").write_text("codex/repair\nPR #9 created: url")
        return ""

    def observe(tid, attempt, evidence):
        observations.append(dict(evidence))
        if evidence.get("stage") == "container_created":
            assert not (directory / "start.barrier").exists()
        return True

    monkeypatch.setattr(supervisor, "supervisor_command", command)
    monkeypatch.setattr(
        supervisor,
        "owned_container",
        Mock(return_value={"running": False, "restarting": False}),
    )
    states = iter(["active", "inactive", "inactive"])
    monkeypatch.setattr(
        supervisor,
        "service_state",
        lambda unit: {"ActiveState": next(states), "ControlGroup": ""},
    )
    monkeypatch.setattr(supervisor.time, "sleep", lambda seconds: None)
    return task, directory, commands, observations, observe


def run(supervisor, simulation, **kwargs):
    task, directory, commands, observations, observe = simulation
    return supervisor.run_supervised(
        task,
        "repair",
        runner="/runner",
        timeout=10,
        observe=kwargs.get("observe", observe),
        owns=kwargs.get("owns", lambda *args: True),
    )


def test_service_and_barrier_ordering_never_certifies_stop(supervisor, simulation):
    output, outcome = run(supervisor, simulation)
    task, directory, commands, observations, observe = simulation
    assert outcome == "runner_returned" and "PR #9" in output
    assert (directory / "start.barrier").exists()
    assert (directory / "container.cid").exists()
    launch = commands[0]
    assert "--scope" not in launch
    assert "--service-type=exec" in launch
    assert "--property=KillMode=control-group" in launch
    assert "--property=Restart=no" in launch
    assert f'--setenv=CODEX_ATTEMPT_ID={task["attempt_id"]}' in launch
    assert all(o["stop_confirmed"] is False for o in observations)
    assert observations[-1]["container_inactive"] is True
    assert not any(c[:2] == ["docker", "rm"] for c in commands)


def test_failed_identity_persistence_never_releases_barrier(supervisor, simulation):
    def observe(tid, attempt, evidence):
        return evidence["stage"] != "container_created"

    output, outcome = run(supervisor, simulation, observe=observe)
    assert outcome == "supervisor_claim_lost"
    assert not (simulation[1] / "start.barrier").exists()
    assert (simulation[1] / "stop.signal").exists()


def test_cancelled_claim_never_releases_barrier(supervisor, simulation):
    owns = Mock(side_effect=[True, True, False])
    _, outcome = run(supervisor, simulation, owns=owns)
    assert outcome == "supervisor_claim_lost"
    assert not (simulation[1] / "start.barrier").exists()


def test_foreign_container_never_stopped(supervisor, simulation, monkeypatch):
    monkeypatch.setattr(supervisor, "owned_container", Mock(side_effect=ValueError("foreign")))
    _, outcome = run(supervisor, simulation)
    assert outcome == "supervisor_failed_stop_unconfirmed"
    assert not any(c[0] == "docker" for c in simulation[2])
    assert not (simulation[1] / "start.barrier").exists()


def test_failed_final_observation_cannot_look_successful(supervisor, simulation):
    _, outcome = run(
        supervisor,
        simulation,
        observe=lambda tid, attempt, e: e["stage"] != "cleanup_observed",
    )
    assert outcome == "supervisor_observation_not_persisted"


def test_preexisting_attempt_directory_refused(supervisor, simulation):
    simulation[1].mkdir()
    with pytest.raises(FileExistsError):
        run(supervisor, simulation)
    assert not simulation[2]


def test_stop_failure_escalates_only_after_identity_recheck(supervisor, simulation, monkeypatch):
    original = supervisor.supervisor_command

    def command(args, timeout=30):
        if args[:2] == ["docker", "stop"]:
            simulation[2].append(args)
            raise RuntimeError("stop failed")
        return original(args, timeout)

    monkeypatch.setattr(supervisor, "supervisor_command", command)
    live = {"running": True, "restarting": False}
    stopped = {"running": False, "restarting": False}
    check = Mock(side_effect=[live, live, live, stopped])
    monkeypatch.setattr(supervisor, "owned_container", check)
    _, outcome = run(supervisor, simulation)
    assert outcome == "runner_returned"
    assert check.call_count == 4
    assert any(c[:2] == ["docker", "kill"] for c in simulation[2])


def test_wrong_service_properties_rejected(supervisor, monkeypatch):
    monkeypatch.setattr(
        supervisor,
        "supervisor_command",
        lambda args: "LoadState=loaded\nKillMode=process\nRestart=no",
    )
    with pytest.raises(ValueError):
        supervisor.service_state("attempt.service")


def test_timeout_never_certifies_stop(supervisor, simulation, monkeypatch):
    ticks = iter([0, 0, 20])
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(supervisor, "service_state", lambda unit: {"ActiveState": "active", "ControlGroup": ""})
    _, outcome = run(supervisor, simulation)
    assert outcome == "supervisor_timeout_stop_unconfirmed"
    assert simulation[3][-1]["stop_confirmed"] is False
    assert (simulation[1] / "stop.signal").exists()
