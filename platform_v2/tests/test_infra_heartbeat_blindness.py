"""A monitor that cannot see must not report what it failed to look at.

`docker inspect` exits non-zero for two unrelated things — "No such object" and
"Cannot connect to the Docker daemon" — and `infra_heartbeat_service` treated both
as "absent". `archie_mcp_gateway` deliberately runs with NO docker socket (read-only
DB role, read tools in-process — see mcp-gateway/gateway.py), so every MCP caller got
this fabricated result against a hub where all 42 containers were running:

    severity  error
    DOWN (9)  network_adguard, archie_comms, kbs_app, kytran-system-operations,
              kytran_creed, media_plex, media_jellyfin, media_samba, archie_tailscale
    reason     "container absent from docker (likely removed)"

Seven of those nine carry `auto_restart_safe: True`, and the agent-loop path files
Tier-2 restart approvals from exactly that field. So the failure mode was not a noisy
false alarm — it was a credible, actionable instruction to restart healthy services.

These tests pin the distinction:

    absent   — a claim about a container  → may alert, may file a restart
    blind    — a claim about the observer → must alert as a BROKEN MONITOR, and
               must be structurally incapable of filing a restart

The scheduled job was never affected (it runs inside archie_platform, which has the
socket). These are the MCP-tool surface.

See KB #285320 and test_infra_heartbeat_networks.py for the sibling Networks==0 defect:
same shape, same lesson — a check that cannot observe correctly must say so rather than
report a confident answer.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

from services.infra_heartbeat_service import (
    CRITICAL_CONTAINERS,
    DockerObserverUnavailable,
    _absent_snapshot,
    _inspect_via_cli,
    _looks_like_daemon_unreachable,
    check_all_critical,
    check_container,
    format_alert_message,
    inspect_container,
)

_SERVICE_PATH = Path(__file__).resolve().parents[1] / "services" / "infra_heartbeat_service.py"

# Verbatim from a real `docker inspect` inside archie_mcp_gateway, where the CLI is
# present and the socket is not.
_REAL_DAEMON_STDERR = (
    "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. " "Is the docker daemon running?"
)
# Verbatim from `docker inspect` for a container that really is gone.
_REAL_NOTFOUND_STDERR = "Error: No such object: nginx_proxy_manager"


def _blind_docker(monkeypatch):
    """Make every subprocess look like a gateway with no docker socket."""

    def _run(cmd, *a, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", _REAL_DAEMON_STDERR)

    monkeypatch.setattr("services.infra_heartbeat_service.subprocess.run", _run)


def _absent_docker(monkeypatch):
    """Make every subprocess look like a genuinely missing container."""

    def _run(cmd, *a, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", _REAL_NOTFOUND_STDERR)

    monkeypatch.setattr("services.infra_heartbeat_service.subprocess.run", _run)


# ---------------------------------------------------------------------------
# The two failures must not be confused at the lowest level
# ---------------------------------------------------------------------------


def test_daemon_unreachable_is_recognised():
    assert _looks_like_daemon_unreachable(_REAL_DAEMON_STDERR) is True


def test_no_such_object_is_not_daemon_unreachable():
    """The trap: both exit non-zero. Only one means 'I cannot see'."""
    assert _looks_like_daemon_unreachable(_REAL_NOTFOUND_STDERR) is False


def test_cli_reports_blindness_when_the_socket_is_missing(monkeypatch):
    """The gateway's exact condition — CLI present, daemon absent."""

    def _run(cmd, *a, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", _REAL_DAEMON_STDERR)

    monkeypatch.setattr("services.infra_heartbeat_service.subprocess.run", _run)

    with pytest.raises(DockerObserverUnavailable):
        _inspect_via_cli("media_plex")


def test_cli_still_reports_absence_when_the_container_is_really_gone(monkeypatch):
    """Genuine absence must keep working — the fix must not neuter the check.

    This is the NPM failure mode (2026-04-18) that the whole service exists for.
    A fix that made absence unreportable would trade a false alarm for a blind spot.
    """

    def _run(cmd, *a, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", _REAL_NOTFOUND_STDERR)

    monkeypatch.setattr("services.infra_heartbeat_service.subprocess.run", _run)

    snap = _inspect_via_cli("media_plex")

    assert snap == _absent_snapshot()


def test_no_docker_client_at_all_is_blind_not_empty(monkeypatch):
    """FileNotFoundError used to return None, which became an absent snapshot."""

    def _run(cmd, *a, **kw):
        raise FileNotFoundError("docker")

    monkeypatch.setattr("services.infra_heartbeat_service.subprocess.run", _run)

    with pytest.raises(DockerObserverUnavailable):
        _inspect_via_cli("media_plex")


# ---------------------------------------------------------------------------
# check_container — a blind observer cannot produce an error record
# ---------------------------------------------------------------------------


def test_blind_observer_is_not_an_error(monkeypatch):
    """`error` is the severity the restart-approval loop keys on. Never blind."""

    def _boom(_name):
        raise DockerObserverUnavailable("no docker socket")

    monkeypatch.setattr("services.infra_heartbeat_service.inspect_container", _boom)

    result = check_container("media_plex", {"tcp_probes": [32400], "auto_restart_safe": True})

    assert result["observer_blind"] is True
    assert result["severity"] == "warning"
    assert result["severity"] != "error"


def test_blind_reason_does_not_claim_absence(monkeypatch):
    """The phrases that made the old output actionable must not come back.

    'absent from docker (likely removed)' is the sentence that reads as a
    diagnosis. Asserting on those exact phrases rather than the bare word
    'absent' — the honest message legitimately says "NOT the same as absent".
    """

    def _boom(_name):
        raise DockerObserverUnavailable("no docker socket")

    monkeypatch.setattr("services.infra_heartbeat_service.inspect_container", _boom)

    result = check_container("media_plex", {"tcp_probes": []})

    reason = result["reason"].lower()
    assert "blind" in reason
    assert "unknown" in reason
    assert "do not restart" in reason
    assert "absent from docker" not in reason
    assert "likely removed" not in reason


def test_blind_record_never_reports_present_false_as_a_finding(monkeypatch):
    """`present: False` must be readable as 'unverified', not 'confirmed gone'.

    The record keeps a uniform shape so consumers do not crash; the reason string
    and observer_blind flag are what carry the truth.
    """

    def _boom(_name):
        raise DockerObserverUnavailable("no docker socket")

    monkeypatch.setattr("services.infra_heartbeat_service.inspect_container", _boom)

    result = check_container("media_plex", {"tcp_probes": []})

    assert result["observer_blind"] is True
    assert result["present"] is False
    assert "UNKNOWN" in result["reason"]


# ---------------------------------------------------------------------------
# check_all_critical — the pass must be self-consistent when blind
# ---------------------------------------------------------------------------


def test_blind_pass_reports_nothing_down(monkeypatch):
    """down_names is the field that becomes a restart instruction."""
    _blind_docker(monkeypatch)

    result = check_all_critical()

    assert result["observer_blind"] is True
    assert result["down_names"] == [], (
        "a blind pass must never name a container as down — that list becomes a " "restart approval"
    )
    assert result["severity"] != "error"


def test_blind_pass_contains_no_error_severity_records(monkeypatch):
    """Structural guarantee: the approval loop iterates records, not down_names.

    agent_loop._run_infra_heartbeat files a Tier-2 restart for every record with
    severity == "error" and auto_restart_safe. Under blindness no record may
    reach that branch, whatever the registry says.
    """
    _blind_docker(monkeypatch)

    result = check_all_critical()

    assert result["containers"], "records should still be produced, flagged blind"
    for record in result["containers"]:
        assert record["severity"] != "error", f"{record['name']} reached error while blind"
        assert record["observer_blind"] is True


def test_blind_pass_counts_no_healthy_either(monkeypatch):
    """`healthy: 10, down: 0` is how blindness would read as an all-clear."""
    _blind_docker(monkeypatch)

    result = check_all_critical()

    assert result["summary_metrics"]["healthy"] == 0
    assert result["summary_metrics"]["down"] == 0
    assert result["summary_metrics"]["blind"] == len(CRITICAL_CONTAINERS)


def test_blind_pass_costs_exactly_one_docker_call(monkeypatch):
    """The pre-flight is a short circuit, not a formality.

    Routing the blind branch back through check_container() still produced
    correct records while costing 1 + 2N failed subprocesses — correct output,
    and a 5-minute job that had rediscovered a fact it already knew N times over.
    Output is what the other tests pin; this one pins the cost.
    """
    calls = []

    def _run(cmd, *a, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", _REAL_DAEMON_STDERR)

    monkeypatch.setattr("services.infra_heartbeat_service.subprocess.run", _run)

    result = check_all_critical()

    assert result["observer_blind"] is True
    assert len(calls) == 1, f"a blind pass made {len(calls)} docker calls, expected exactly 1: {calls}"
    assert result["containers"], "the short circuit must still emit one record per entry"
    assert len(result["containers"]) == len(CRITICAL_CONTAINERS)


def test_blind_records_never_claim_to_have_probed(monkeypatch):
    """No probe results exist under blindness — the record must not imply any."""
    _blind_docker(monkeypatch)

    result = check_all_critical()

    for record in result["containers"]:
        assert record["tcp_probes"] == {}, "no probe ran, so no probe result may appear"
        assert record["http_probe"] is None
        assert record["state"] is None
        assert record["started_at"] is None


def test_blind_pass_names_blindness_in_its_reasons(monkeypatch):
    _blind_docker(monkeypatch)

    result = check_all_critical()

    assert any("MONITORING BLIND" in r for r in result["reasons"])
    assert any("UNKNOWN" in r for r in result["reasons"])


# ---------------------------------------------------------------------------
# The alert text — what a human actually reads at 3am
# ---------------------------------------------------------------------------


def test_blind_alert_does_not_render_a_down_list(monkeypatch):
    _blind_docker(monkeypatch)

    body = format_alert_message(check_all_critical())

    assert "MONITORING BLIND" in body
    assert "DOWN:" not in body, "a blind pass must not render a DOWN section"
    assert "0 down" not in body, "'0 down · 0 healthy' reads as a healthy fleet"


def test_blind_alert_states_it_is_not_a_missing_container_report(monkeypatch):
    _blind_docker(monkeypatch)

    body = format_alert_message(check_all_critical())

    assert "NOT a report of missing containers" in body


def test_sighted_pass_alert_is_unchanged(monkeypatch):
    """The normal rendering must not regress — blindness is an added branch."""
    monkeypatch.setattr(
        "services.infra_heartbeat_service.inspect_container",
        lambda _n: {
            "present": True,
            "state": "running",
            "health": "healthy",
            "started_at": "2026-10-01T00:00:00Z",
            "networks": ["host"],
            "network_mode": "host",
        },
    )
    monkeypatch.setattr("services.infra_heartbeat_service.docker_observer_available", lambda: None)

    body = format_alert_message(check_all_critical())

    # Asserted against the live registry length, not a hardcoded 10 — Layer 3 grew
    # the registry to 36 entries, and a test pinned to the old count would fail on
    # a correct change. What matters is the SHAPE of a sighted report.
    assert "MONITORING BLIND" not in body
    assert "Severity: *INFO*" in body
    assert f"{len(CRITICAL_CONTAINERS)} healthy ({len(CRITICAL_CONTAINERS)} watched)" in body
    assert " down" in body.split("·")[0] or "0 down" in body


# ---------------------------------------------------------------------------
# Proof the suite discriminates — pre-fix code must FAIL these tests.
# Per .claude/rules/repair-bay.md: a test that cannot fail is worse than none.
# The defect is reintroduced in an in-memory COPY; the live file is untouched.
# ---------------------------------------------------------------------------


def _load_prefix_module():
    """Load a copy of the service with the absent/blind conflation restored.

    Three sites make up the fix, and all three must be reverted for a faithful
    reproduction — reverting only the CLI check leaves the pre-flight in place,
    which catches the blindness first and the copy then behaves correctly, making
    every discriminating assertion below pass vacuously.

      1. _inspect_via_cli  — non-zero exit no longer splits daemon-vs-not-found
      2. inspect_container — no-client fallback raises instead of claiming absence
      3. check_all_critical — the pre-flight short-circuit did not exist pre-fix
    """
    source = _SERVICE_PATH.read_text()

    reverted = source
    for pattern, replacement, label in (
        (
            # Whitespace-tolerant: Black is free to wrap the `raise` across
            # lines, which silently turned this reintroduction into a no-op and
            # made the whole proof vacuous. Pinning the exact old formatting
            # meant the test failed with "reverted 0" instead — which is what
            # caught it, but only by accident of the assertion below.
            r"        stderr = \(result\.stderr or \"\"\)\.strip\(\)\n"
            r"        if _looks_like_daemon_unreachable\(stderr\):\n"
            r"            raise DockerObserverUnavailable\(\s*"
            r"f?\"docker CLI cannot reach daemon: \{stderr\[:300\]\}\"\s*\)\n",
            "",
            "CLI daemon check",
        ),
        (
            r'    raise DockerObserverUnavailable\("no usable docker client \(SDK and CLI both failed\)"\)\n',
            "    return _absent_snapshot()\n",
            "inspect_container fallback",
        ),
        (
            r"\n    # Pre-flight:.*?\n    per_container: List\[Dict\[str, Any\]\] = \[\]",
            "\n    per_container: List[Dict[str, Any]] = []",
            "check_all_critical pre-flight",
        ),
    ):
        reverted, n = re.subn(pattern, replacement, reverted, flags=re.DOTALL)
        assert n == 1, (
            f"expected to revert exactly 1 {label}, reverted {n}. "
            "The guard was renamed or reshaped — update this reintroduction."
        )

    # Assert on the CALL SITES, not prose: these exact fragments occur nowhere else.
    assert (
        'raise DockerObserverUnavailable(f"docker CLI cannot reach daemon' not in reverted
    ), "defect was not actually reintroduced — the CLI guard survived the revert"
    assert "# Pre-flight:" not in reverted, "defect was not actually reintroduced — the pre-flight survived the revert"

    spec = importlib.util.spec_from_loader("_prefix_blind", loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__file__"] = str(_SERVICE_PATH)
    exec(compile(reverted, "<prefix_blind>", "exec"), module.__dict__)
    return module


def test_prefix_code_reports_the_fabricated_outage(monkeypatch):
    """Reproduction of the real incident, in-memory.

    Pre-fix code in a gateway-shaped process returns severity=error with named
    containers DOWN. That is the behaviour every test above exists to forbid, and
    it is what a caller would have seen against a fully healthy hub.
    """
    prefix = _load_prefix_module()

    def _run(cmd, *a, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", _REAL_DAEMON_STDERR)

    monkeypatch.setattr(prefix.subprocess, "run", _run)

    result = prefix.check_all_critical()

    assert result["down_names"], "pre-fix code found nothing down — reintroduction is wrong"
    assert result["severity"] == "error"
    assert not result.get("observer_blind"), "pre-fix code had no blindness concept"

    # And the records reach the branch that files restart approvals.
    approvable = [r["name"] for r in result["containers"] if r["severity"] == "error" and r.get("auto_restart_safe")]
    assert approvable, (
        "pre-fix code produced no auto-restart-eligible container — the reintroduction "
        "does not reproduce the actionable part of the incident"
    )
