"""A registry entry nobody can act on is a comment with a severity.

Layer 1 (#3570) fixed V.I.G.I.L. reporting nine healthy containers as DOWN from a
process that could not see docker. Layer 3 is the other half of the same class of
mistake: detection that looks like coverage.

## The six approvals that could not execute

`restart_container()` shells out to `docker compose up -d --no-deps <service>` with
`cwd=/mnt/archie_brain`. With no `-f`, that reads only that directory's compose file —
27 services. Six of the ten original registry entries named a service that is not in
it:

    entry                        names            actually lives in
    kbs_app                      kbs_app          kytran-business-suite/docker-compose.yml
    kytran_creed                 kytran_creed     kytran-creed/docker-compose.yml
    media_plex                   media_plex       media-stack/docker-compose.yml  (as `plex`)
    media_jellyfin               media_jellyfin   media-stack/docker-compose.yml  (as `jellyfin`)
    kytran-system-operations     (same)           kytran-server-manager/docker-compose.yml
    network_adguard              (same)           network-tools/docker-compose.yml

Verified with `docker compose up --dry-run` — each returns "no such service". So a
human could approve a Tier-2 restart from Telegram, the job would burn the approval,
and the container would stay down. An approval that cannot execute is worse than no
approval: it spends attention and manufactures the appearance of automation.

`test_compose_wiring_resolves` below is the regression guard. It caught two more
wrong service names the moment these entries were written (`redis` and `ntopng`,
guessed, where the real names are `network_redis` and `network_ntopng`) — which is
the argument for having the test rather than a review checklist.

## The other half: probe honesty

A probe that cannot reach the thing it names is an all-clear for the wrong service.
The sharpest case: `archie_scheduler` publishes nothing, so the only thing on
192.168.1.200:3000 is `archie_platform`. Probing 3000 for the scheduler would report
the scheduler healthy whenever the platform is up. It gets `tcp_probes: []` and relies
on its own healthcheck instead — a real psycopg2 connect.

Same reasoning for `kbs_postgres`: nothing is published on 5432 except
`archie_database`, so a 5432 probe would light up green for the wrong database.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from services.infra_heartbeat_service import (
    CRITICAL_CONTAINERS,
    _PROBE_HOST_FROM_CONTAINER,
    restart_container,
)

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

REPO_ROOT = Path("/mnt/archie_brain")


# ---------------------------------------------------------------------------
# The compose wiring must resolve — this is the whole point of the layer
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(not REPO_ROOT.exists(), reason="compose files are on the hub, not in a checkout")


def _services_in(path: str) -> set:
    with open(path) as fh:
        return set((yaml.safe_load(fh).get("services") or {}).keys())


def test_compose_wiring_resolves():
    """Every entry's compose_service must exist in ITS OWN compose file.

    The historical bug is specifically the mismatch: the service exists, but in a
    different stack's file. Checking only "is this service somewhere" would pass
    while the restart still failed.
    """
    if yaml is None:
        pytest.skip("pyyaml unavailable")

    broken = []
    for name, cfg in CRITICAL_CONTAINERS.items():
        compose_file = cfg.get("compose_file")
        service = cfg.get("compose_service", name)

        if not compose_file:
            # Detection-only is legitimate — but it must not claim restart safety.
            if cfg.get("auto_restart_safe"):
                broken.append(f"{name}: no compose_file but auto_restart_safe=True")
            continue

        if not os.path.exists(compose_file):
            broken.append(f"{name}: compose file does not exist: {compose_file}")
            continue

        if service not in _services_in(compose_file):
            broken.append(f"{name}: {service!r} not a service in {compose_file}")

    assert not broken, "registry entries whose restart could never execute:\n" + "\n".join(f"  {b}" for b in broken)


def test_every_registry_container_exists_on_this_hub():
    """A name that is not a running container can only ever report 'absent'.

    That is the registry's whole failure mode in one assertion: if the container
    is genuinely gone from the fleet, this entry is pure noise and will file
    restart approvals for something that no longer exists.

    On-demand containers are exempt — archie_comfyui is *supposed* to be stopped
    while idle (it wakes for SDXL generation), which check_container already
    treats as normal rather than a fault. A test that demanded it be running
    would contradict the production behaviour it is meant to pin.
    """
    import subprocess

    running = set(
        subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.split()
    )
    if not running:
        pytest.skip("docker unavailable in this environment")

    stale = [n for n, c in CRITICAL_CONTAINERS.items() if n not in running and c.get("service_class") != "on-demand"]
    assert not stale, f"registry names not present as running containers: {stale}"


def test_no_duplicate_compose_service_targets():
    """Two entries pointing at one compose service means one restart fixes both
    claims — or the second silently no-ops while claiming success."""
    if yaml is None:
        pytest.skip("pyyaml unavailable")

    seen: dict = {}
    dupes = []
    for name, cfg in CRITICAL_CONTAINERS.items():
        compose_file = cfg.get("compose_file")
        service = cfg.get("compose_service", name)
        if not compose_file:
            continue
        key = (compose_file, service)
        if key in seen:
            dupes.append(f"{seen[key]} and {name} both target {service} in {compose_file}")
        seen[key] = name
    assert not dupes, "\n".join(dupes)


# ---------------------------------------------------------------------------
# restart_container refuses rather than guessing
# ---------------------------------------------------------------------------


def test_restart_accepts_container_name_and_service_name(monkeypatch):
    """Callers hold both spellings: the agent loop files `compose_service` from the
    record, while a human approving from Telegram sees the container name.

    media_plex is the interesting case — the two spellings differ, which is exactly
    why both have to resolve to the same entry.
    """
    import services.infra_heartbeat_service as svc

    commands = []

    class _Done:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(svc.subprocess, "run", lambda cmd, *a, **kw: (commands.append(cmd), _Done())[1])

    assert svc.CRITICAL_CONTAINERS["media_plex"]["compose_service"] == "plex"

    by_container = restart_container("media_plex")
    by_service = restart_container("plex")

    assert by_container["success"] is True, by_container
    assert by_service["success"] is True, by_service
    # Same entry, same target — not two different lookups that happen to pass.
    assert by_container["compose_service"] == by_service["compose_service"] == "plex"
    assert commands[0] == commands[1]
    assert commands[0][-1] == "plex"


def test_restart_rejects_unknown_container():
    result = restart_container("definitely_not_a_registered_container")
    assert result["success"] is False
    assert "not in the critical container registry" in result["error"]


def test_restart_refuses_entry_with_no_compose_file(monkeypatch):
    """archie_hub_caddy has no compose project. It must refuse, not fall back to a
    cwd-only invocation — that fallback is the original bug."""
    calls = []

    def _run(cmd, *a, **kw):
        calls.append(cmd)
        raise AssertionError("must not shell out for a detection-only entry")

    monkeypatch.setattr("services.infra_heartbeat_service.subprocess.run", _run)

    result = restart_container("archie_hub_caddy")

    assert result["success"] is False
    assert "detection-only" in result["error"]
    assert not calls, "it shelled out anyway"


def test_restart_builds_command_with_explicit_compose_file(monkeypatch):
    """The regression itself: -f must be present, and cwd must be the owning dir."""
    import services.infra_heartbeat_service as svc

    seen = {}

    class _Done:
        returncode = 0
        stdout = "Container media_plex  Started"
        stderr = ""

    def _run(cmd, *a, **kw):
        seen["cmd"] = cmd
        seen["cwd"] = kw.get("cwd")
        return _Done()

    monkeypatch.setattr(svc.subprocess, "run", _run)

    # media_plex's service name is `plex`, and it lives in media-stack/.
    result = restart_container("media_plex")

    assert result["success"] is True
    assert result["compose_service"] == "plex"
    assert "-f" in seen["cmd"], f"compose file not passed: {seen['cmd']}"
    assert seen["cmd"][seen["cmd"].index("-f") + 1].endswith("media-stack/docker-compose.yml")
    assert seen["cmd"][-1] == "plex"
    assert seen["cwd"].endswith("media-stack")


def test_restart_fails_loudly_when_compose_file_vanished(monkeypatch):
    """A compose file that is gone must not silently become a cwd-only restart."""
    monkeypatch.setitem(
        __import__("services.infra_heartbeat_service", fromlist=["CRITICAL_CONTAINERS"]).CRITICAL_CONTAINERS,
        "media_plex",
        {
            **CRITICAL_CONTAINERS["media_plex"],
            "compose_file": "/nonexistent/docker-compose.yml",
        },
    )

    result = restart_container("media_plex")

    assert result["success"] is False
    assert "does not exist" in result["error"]


# ---------------------------------------------------------------------------
# Probe honesty
# ---------------------------------------------------------------------------


def test_scheduler_has_no_tcp_probe():
    """Nothing is published for archie_scheduler; :3000 on the probe host is
    archie_platform. A probe here would report the scheduler healthy whenever the
    platform was up — an all-clear for the wrong process."""
    assert CRITICAL_CONTAINERS["archie_scheduler"]["tcp_probes"] == []


def test_kbs_postgres_has_no_tcp_probe():
    """The only 5432 on the probe host is archie_database."""
    assert CRITICAL_CONTAINERS["kbs_postgres"]["tcp_probes"] == []


def test_entries_without_probes_have_another_signal():
    """An entry with no tcp_probe is only legitimate if something else can see it.

    Three possibilities, all of which must be explicit:
      - a docker healthcheck (consumed by check_container's health branch)
      - service_class 'on-demand' (absent while idle is the correct state)
      - an explicit presence_only_reason saying what is lost

    The third is a known, accepted limitation — kbs_postgres, kbs_redis and
    network_redis sit on isolated or localhost-only networks and have no
    healthcheck, so they detect ABSENCE but never a wedged process. That is
    worse than a probe, and pretending otherwise by leaving the field off is
    how the "looks monitored, isn't" class of bug happens. Requiring the
    reason means the gap is documented and reviewable, and the comment tells
    the next person how to close it.
    """
    import subprocess

    inspect = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            "{{if .Config.Healthcheck}}hc{{else}}noc{{end}}",
            *CRITICAL_CONTAINERS,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if inspect.returncode != 0:
        pytest.skip("docker unavailable")

    unexplained = []
    for name, health in zip(CRITICAL_CONTAINERS, inspect.stdout.split()):
        cfg = CRITICAL_CONTAINERS[name]
        if cfg.get("tcp_probes"):
            continue
        if health == "hc" or cfg.get("service_class") == "on-demand":
            continue
        reason = cfg.get("presence_only_reason")
        if not reason:
            unexplained.append(
                f"{name} (healthcheck: {health}) — no probe, no healthcheck, and no "
                "presence_only_reason explaining the gap"
            )
        else:
            # A reason must be actionable: it should say what to fix.
            assert len(reason) > 40, f"{name}: presence_only_reason is too vague: {reason!r}"

    assert not unexplained, "these entries can only detect absence, and do not say so:\n" + "\n".join(
        f"  {u}" for u in unexplained
    )


def test_presence_only_reason_names_how_to_close_the_gap():
    """The reason must be actionable, not just an apology."""
    for name, cfg in CRITICAL_CONTAINERS.items():
        reason = cfg.get("presence_only_reason")
        if not reason:
            continue
        lowered = reason.lower()
        assert "healthcheck" in lowered, (
            f"{name}: presence_only_reason should point at the fix (a healthcheck), "
            f"not just the limitation: {reason!r}"
        )


def test_no_two_entries_probe_the_same_port():
    """Two entries probing one port means one of them is measuring the other."""
    seen: dict = {}
    clashes = []
    for name, cfg in CRITICAL_CONTAINERS.items():
        for port in cfg.get("tcp_probes", []):
            if port in seen:
                clashes.append(f"{seen[port]} and {name} both probe {_PROBE_HOST_FROM_CONTAINER}:{port}")
            seen[port] = name
    assert not clashes, "\n".join(clashes)


def test_host_mode_containers_do_not_borrow_each_others_ports():
    """Regression guard for a real misattribution made while writing this layer.

    archie_hub_caddy, network_ntopng, network_adguard and media_plex all run in
    the HOST network namespace. `ss -lnt` executed inside any of them therefore
    reports every host listener, not its own — so ntopng's `-w 3001` looks like
    it belongs to Caddy, and it does not.

    Guessing here produces a probe that stays green while the service is dead,
    which is worse than no probe at all. So the two ports are pinned explicitly
    to their real owners, with the evidence recorded.

    If a future compose change moves either port, this fails and the new owner
    has to be established the same way — from the process's own argv, not from
    a host-wide netstat.
    """
    assert CRITICAL_CONTAINERS["archie_hub_caddy"]["tcp_probes"] == [80], (
        "Caddy is host-mode and its site blocks are HTTP-only (auto_https off) — "
        "its listener is :80. See the entry's comment for the 3001 trap."
    )
    assert CRITICAL_CONTAINERS["network_ntopng"]["tcp_probes"] == [
        3001
    ], "ntopng runs `-w 3001` per its own argv; :3001 belongs to ntopng."
    assert CRITICAL_CONTAINERS["archie_platform"]["tcp_probes"] == [
        3000
    ], "archie_platform owns :3000 — the reason archie_scheduler cannot be probed."


def test_registry_tiers_are_labelled():
    """Tier 1 is the hub spine. Everything must declare which it is, so the next
    person adding an entry has to make the choice consciously."""
    unlabelled = [n for n, c in CRITICAL_CONTAINERS.items() if c.get("tier") not in (1, 2)]
    assert not unlabelled, f"entries without a tier: {unlabelled}"


def test_hub_spine_is_watched():
    """The registry existed for a year without the hub's own database in it.

    Everything else's failure traces back to one of these; if the spine is
    unwatched the monitor is decorative at exactly the moment it matters most.
    """
    for essential in (
        "archie_database",
        "archie_platform",
        "archie_scheduler",
        "archie_mcp_gateway",
        "archie_headscale",
        "archie_comms",
    ):
        assert essential in CRITICAL_CONTAINERS, f"{essential} is not watched"


def test_monitoring_stack_is_watched():
    """If cadvisor/dozzle/nagios are down, V.I.G.I.L. is the only reporter and
    nothing is watching V.I.G.I.L."""
    for monitor in ("monitoring_cadvisor", "monitoring_dozzle", "monitoring_nagios"):
        assert monitor in CRITICAL_CONTAINERS, f"{monitor} is not watched"


def test_scanner_fleet_is_deliberately_excluded():
    """security_zap's healthcheck curls `/`, which ZAP answers non-2xx — it has been
    `unhealthy` continuously while serving. Adding it as-is would manufacture a
    permanent false alarm, which is worse than not watching it."""
    for scanner in ("security_zap", "security_nmap", "security_nuclei"):
        assert scanner not in CRITICAL_CONTAINERS, (
            f"{scanner} was added — its healthcheck must be fixed first, or this " "fires a permanent false alarm"
        )


def test_dev_lanes_are_not_watched():
    """A coding lane with no active session is *supposed* to be down."""
    for lane in (
        "archie_opencode_terminal",
        "archie_opencode_terminal_gf",
        "archie_opencode_terminal_host",
        "archie_codex_terminal",
    ):
        assert lane not in CRITICAL_CONTAINERS, f"{lane} is not a health signal"
