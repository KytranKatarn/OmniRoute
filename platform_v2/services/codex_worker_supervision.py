"""Default-off host supervision adapter. Observations never authorize replacement.

User-systemd execution is a coordination mechanism, not a validated receipt
issuer boundary. Host provisioning and authenticated append-only storage remain
prerequisites for trusted stop evidence.
"""

import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import uuid


def supervisor_command(args: list[str], timeout: int = 30) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Command output may contain task prose or credentials. Do not echo it.
        raise RuntimeError(f"Supervisor command failed: {args[0]}")
    return result.stdout.strip()


def owned_container(container_id: str, task_id: int, attempt_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", container_id):
        raise ValueError("Expected full container ID")
    # Whitelist inspect fields: never fetch environment, command, mounts or logs.
    fmt = (
        '{"id":{{json .Id}},"labels":{{json .Config.Labels}},'
        '"running":{{json .State.Running}},"restarting":{{json .State.Restarting}},'
        '"restart":{{json .HostConfig.RestartPolicy.Name}}}'
    )
    data = json.loads(supervisor_command(["docker", "inspect", "--format", fmt, container_id]))
    expected = {
        "codex.attempt.id": str(uuid.UUID(attempt_id)),
        "codex.task.id": str(int(task_id)),
        "codex.host.id": socket.gethostname(),
        "codex.host.boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    }
    if data.get("id") != container_id or any((data.get("labels") or {}).get(k) != v for k, v in expected.items()):
        raise ValueError("Container ownership mismatch")
    if data.get("restart") != "no":
        raise ValueError("Container restart must be disabled")
    if type(data.get("running")) is not bool or type(data.get("restarting")) is not bool:
        raise ValueError("Malformed container state")
    return data


def service_state(unit: str) -> dict:
    out = supervisor_command(
        [
            "systemctl",
            "--user",
            "show",
            unit,
            "--property=LoadState,ActiveState,SubState,ControlGroup,KillMode,Restart",
        ]
    )
    data = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if data.get("LoadState") != "loaded" or data.get("KillMode") != "control-group" or data.get("Restart") != "no":
        raise ValueError("Unverified service properties")
    if data.get("ActiveState") not in {"active", "inactive", "failed", "activating", "deactivating", "reloading"}:
        raise ValueError("Unverified service state")
    return data


def run_supervised(task: dict, prompt: str, *, runner: str, timeout: int, observe, owns) -> tuple[str, str]:
    """Default-off user-service integration; never certifies stopped execution.

    User-service containment has NOT been approved as an issuer security boundary.
    Evidence remains diagnostic until host provisioning and authenticated receipt
    storage are implemented. Keep container/journal files for later investigation.
    """
    tid, attempt = int(task["id"]), str(uuid.UUID(task["attempt_id"]))
    unit = f"archie-codex-attempt-{attempt}.service"
    runtime = Path(f"/run/user/{os.getuid()}")
    info = runtime.lstat()
    if runtime.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Unsafe runtime directory")
    directory = runtime / f"codex-attempt-{attempt}"
    directory.mkdir(mode=0o700)  # exclusive attempt; never accept pre-existing state
    log = directory / "runner.log"
    log.touch(mode=0o600, exist_ok=False)
    cidfile = directory / "container.cid"
    observation = {"unit": unit, "stage": "prepared", "stop_confirmed": False}
    if not observe(tid, attempt, observation):
        return "", "supervisor_claim_lost"
    outcome = "supervisor_failed_stop_unconfirmed"
    container_id = None
    launched = False
    try:
        if not owns(tid, attempt):
            return "", "supervisor_claim_lost"
        launched = True  # launch may succeed even if its client loses the response
        supervisor_command(
            [
                "systemd-run",
                "--user",
                "--quiet",
                f"--unit={unit}",
                "--service-type=exec",
                "--property=KillMode=control-group",
                "--property=Restart=no",
                "--property=TimeoutStopSec=10s",
                f"--property=RuntimeMaxSec={int(timeout)}s",
                f"--property=StandardOutput=append:{log}",
                f"--property=StandardError=append:{log}",
                "--setenv=CODEX_SUPERVISED=1",
                f"--setenv=CODEX_ATTEMPT_ID={attempt}",
                f"--setenv=CODEX_TASK_ID={tid}",
                runner,
                prompt,
            ]
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not owns(tid, attempt):
                outcome = "supervisor_claim_lost"
                break
            state = service_state(unit)
            if container_id is None and cidfile.exists():
                stat = cidfile.lstat()
                if cidfile.is_symlink() or stat.st_uid != os.getuid() or stat.st_size != 64:
                    raise ValueError("Unsafe cidfile")
                container_id = cidfile.read_text()
                owned_container(container_id, tid, attempt)
                observation.update(container_id=container_id, stage="container_created")
                if not observe(tid, attempt, observation) or not owns(tid, attempt):
                    outcome = "supervisor_claim_lost"
                    break
                # Atomic creation only AFTER identity is durable and ownership rechecked.
                (directory / "start.barrier").touch(mode=0o600, exist_ok=False)
            if state["ActiveState"] in {"inactive", "failed"}:
                outcome = "runner_returned" if container_id else "supervisor_no_container"
                break
            time.sleep(1)
        else:
            outcome = "supervisor_timeout_stop_unconfirmed"
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        observation["error"] = "supervision_unconfirmed"
    finally:
        observation["stage"] = "cleanup_observed"
        if launched:
            try:
                (directory / "stop.signal").touch(mode=0o600, exist_ok=False)
                supervisor_command(["systemctl", "--user", "stop", unit], timeout=30)
                state = service_state(unit)
                observation["service_inactive"] = state["ActiveState"] in {
                    "inactive",
                    "failed",
                }
                # Cgroup disappearance is UNKNOWN here, not proof of reaping.
                observation["cgroup_empty"] = False
                group = state.get("ControlGroup", "")
                if group.startswith("/") and ".." not in Path(group).parts:
                    events = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.events"
                    observation["cgroup_empty"] = "populated 0" in events.read_text().splitlines()
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                observation["service_cleanup"] = "unknown"
            try:
                if container_id is None and cidfile.exists():
                    if cidfile.is_symlink() or cidfile.stat().st_size != 64:
                        raise ValueError("Unsafe recovery cidfile")
                    container_id = cidfile.read_text()
                if container_id:
                    data = owned_container(container_id, tid, attempt)
                    if data["running"] or data["restarting"]:
                        try:
                            supervisor_command(["docker", "stop", "--time=10", container_id])
                        except (RuntimeError, subprocess.TimeoutExpired):
                            pass  # Re-inspect exact identity before kill escalation.
                        data = owned_container(container_id, tid, attempt)
                    if data["running"] or data["restarting"]:
                        supervisor_command(["docker", "kill", container_id])
                        data = owned_container(container_id, tid, attempt)
                    observation["container_inactive"] = not data["running"] and not data["restarting"]
                    observation["container_id"] = container_id
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                observation["container_cleanup"] = "unknown"
        if not observe(tid, attempt, observation):
            outcome = "supervisor_observation_not_persisted"
    return log.read_text(), outcome
