"""#5409 — a container can be 'running' and attached to NO network.

Twice on this hub a container was up, its daemon listening and its ports
correctly published, while `NetworkSettings.Networks` was empty — making it
completely unreachable:

  * archie_tailscale — ~23 days (RestartCount 219)
  * media_samba      — ~25 days (healthcheck FailingStreak 3014)

`State.Status == "running"` is what made both invisible. These tests pin the
detection AND the registry membership, because a check whose subject is not in
CRITICAL_CONTAINERS is unmonitored while appearing monitored.

See KB #285320 and .claude/rules/ (mistake_container-running-but-networks-zero).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from services.infra_heartbeat_service import (
    CRITICAL_CONTAINERS,
    DockerObserverUnavailable,
    _absent_snapshot,
    _shares_network_namespace,
    check_container,
    inspect_container,
)

_SERVICE_PATH = Path(__file__).resolve().parents[1] / "services" / "infra_heartbeat_service.py"


def _snap(**overrides):
    """A 'running and fine' snapshot, overridable per test."""
    base = {
        "present": True,
        "state": "running",
        "health": "healthy",
        "started_at": "2026-07-29T00:00:00Z",
        "networks": ["archie_network"],
        "network_mode": "archie_network",
    }
    base.update(overrides)
    return base


def _patch_inspect(monkeypatch, snap):
    monkeypatch.setattr("services.infra_heartbeat_service.inspect_container", lambda _name: snap)


# ---------------------------------------------------------------------------
# The defect itself
# ---------------------------------------------------------------------------


def test_running_with_zero_networks_is_an_error(monkeypatch):
    """The media_samba / archie_tailscale case: running, but unreachable."""
    _patch_inspect(monkeypatch, _snap(networks=[], network_mode="bridge"))

    result = check_container("media_samba", {"description": "smb", "tcp_probes": []})

    assert result["severity"] == "error"
    assert "no network" in result["reason"].lower()


def test_zero_networks_beats_a_healthy_healthcheck(monkeypatch):
    """`health: healthy` must not launder an unreachable container.

    media_samba reported healthy for long stretches while its FailingStreak
    climbed to 3014 — process-level health says nothing about reachability.
    """
    _patch_inspect(monkeypatch, _snap(networks=[], network_mode="bridge", health="healthy"))

    result = check_container("media_samba", {"tcp_probes": []})

    assert result["severity"] == "error"


def test_zero_networks_checked_before_probes(monkeypatch):
    """The reason must name the network fault, not a generic probe failure.

    Probes are unreliable in their own right (host->own-published-port hairpin
    is broken under userland-proxy=false), so an unreachable container must not
    be reported as merely 'probes failed'.
    """
    _patch_inspect(monkeypatch, _snap(networks=[], network_mode="bridge"))

    # Port 9 (discard) is closed — if probes ran first this would read as a
    # probe failure and be downgraded to a warning.
    result = check_container("media_samba", {"tcp_probes": [9]})

    assert result["severity"] == "error"
    assert "no network" in result["reason"].lower()
    assert result["tcp_probes"] == {}, "probes should not have run"


# ---------------------------------------------------------------------------
# The carve-out — deliberate namespace sharing is NOT a fault
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["container:abc123", "service:gluetun"])
def test_shared_network_namespace_is_not_a_fault(monkeypatch, mode):
    """qBittorrent behind gluetun (merged PR #2547) has zero networks BY DESIGN.

    `network_mode: service:gluetun` in compose becomes `container:<id>` in the
    inspect output. Flagging it would page on a container working as intended.
    """
    _patch_inspect(monkeypatch, _snap(networks=[], network_mode=mode))

    result = check_container("qbittorrent", {"tcp_probes": []})

    assert result["severity"] != "error"
    assert "no network" not in (result["reason"] or "").lower()


def test_host_mode_is_not_treated_as_shared_namespace():
    """host mode reports one network entry ('host'), so it needs no carve-out.

    Verified on this hub against archie_hub_caddy, media_plex, network_ntopng
    and network_adguard — all `mode=host`, all `nets=1`. Carving host out here
    would blind the check to a host-mode container that really lost its network.
    """
    assert _shares_network_namespace("host") is False
    assert _shares_network_namespace(None) is False
    assert _shares_network_namespace("bridge") is False
    assert _shares_network_namespace("archie_network") is False


def test_normal_container_with_networks_is_not_flagged(monkeypatch):
    _patch_inspect(monkeypatch, _snap())

    result = check_container("archie_platform", {"tcp_probes": []})

    assert result["severity"] == "info"


# ---------------------------------------------------------------------------
# Snapshot contract — every producer must supply the keys the check reads
# ---------------------------------------------------------------------------


def test_absent_snapshot_carries_the_network_keys():
    """A snapshot missing these keys would make the check read None and pass."""
    snap = _absent_snapshot()
    assert snap["networks"] == []
    assert snap["network_mode"] is None
    assert snap["present"] is False


def test_both_inspectors_failing_reports_blindness_not_absence(monkeypatch):
    """CHANGED CONTRACT — this test used to assert the opposite.

    It previously required `inspect_container` to return an ABSENT snapshot when
    neither inspector produced one. That is precisely the defect: a caller with
    no docker access (archie_mcp_gateway) came back with present=False for every
    container, which check_container rendered as "absent from docker (likely
    removed)" at severity=error. All 42 containers were actually running.

    The snapshot-shape contract above still holds for genuine absence — it is
    `_absent_snapshot()`, not the no-client case, that must carry the keys.
    """
    monkeypatch.setattr("services.infra_heartbeat_service._inspect_via_sdk", lambda _n: None)
    monkeypatch.setattr("services.infra_heartbeat_service._inspect_via_cli", lambda _n: None)

    with pytest.raises(DockerObserverUnavailable):
        inspect_container("nonexistent")


# ---------------------------------------------------------------------------
# Registry — detection is decorative if its subjects are not watched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["media_samba", "archie_tailscale"])
def test_containers_that_actually_failed_this_way_are_monitored(name):
    """Both Networks==0 incidents were on containers absent from the registry.

    Without these entries the detection above would have caught neither.
    """
    assert name in CRITICAL_CONTAINERS


def test_media_samba_is_not_auto_restart_safe():
    """It is a bare `docker run` with no compose service (#5410).

    restart_container() shells `docker compose up -d --no-deps <svc>`, which
    would fail on every attempt — the nginx_proxy_manager revival-loop shape.
    Flip this only when #5410 lands a real compose service.
    """
    assert CRITICAL_CONTAINERS["media_samba"]["auto_restart_safe"] is False


def test_new_entries_have_no_tcp_probes():
    """media_samba publishes on 100.64.0.4:445, not the probe host.

    Probing 192.168.1.200:445 would report a false failure; both containers
    have working docker healthchecks, which check_container already consumes.
    """
    assert CRITICAL_CONTAINERS["media_samba"]["tcp_probes"] == []
    assert CRITICAL_CONTAINERS["archie_tailscale"]["tcp_probes"] == []


# ---------------------------------------------------------------------------
# Proof the suite discriminates — pre-fix code must FAIL these tests.
# Per .claude/rules/repair-bay.md: a test that cannot fail is worse than none.
# The defect is reintroduced in an in-memory COPY; the live file is untouched.
# ---------------------------------------------------------------------------


def _load_prefix_module():
    """Load a copy of the service with the network check stripped out."""
    source = _SERVICE_PATH.read_text()
    stripped, n = re.subn(
        r"\n    if not snap\.get\(\"networks\"\).*?\n        return result\n",
        "\n",
        source,
        flags=re.DOTALL,
    )
    assert n == 1, (
        f"expected to strip exactly 1 network-check block, stripped {n}. "
        "The guard was renamed or reshaped — update this reintroduction."
    )
    # Assert on the CALL SITE, not on prose. Both "no network" and "attached to
    # NO network" also occur in the surrounding docstring and comments, so
    # grepping for either reports "defect not reintroduced" on a correct strip.
    # This call appears only inside the guard being removed.
    assert (
        "_shares_network_namespace(snap.get(" not in stripped
    ), "defect was not actually reintroduced — the guard survived the strip"

    spec = importlib.util.spec_from_loader("_prefix_heartbeat", loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__file__"] = str(_SERVICE_PATH)
    exec(compile(stripped, "<prefix_heartbeat>", "exec"), module.__dict__)
    return module


def test_prefix_code_misses_the_defect(monkeypatch):
    """Without the guard, a container with zero networks reads as healthy.

    This is the assertion that proves test_running_with_zero_networks_is_an_error
    is meaningful rather than vacuously true.
    """
    prefix = _load_prefix_module()
    monkeypatch.setitem(
        prefix.__dict__,
        "inspect_container",
        lambda _n: _snap(networks=[], network_mode="bridge"),
    )

    result = prefix.check_container("media_samba", {"tcp_probes": []})

    assert result["severity"] != "error", (
        "pre-fix code unexpectedly flagged this — the reintroduction is wrong, " "so the real test proves nothing"
    )
    assert result["severity"] == "info"
