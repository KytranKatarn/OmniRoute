"""DR readiness probes must measure the path Beacon uses — scripts/dr/failover.sh.

Regression cover for the loopback-bind trap. failover.sh gates the creed. (:8086)
and mesh. (:8095) Beacon flips on "is the service actually serving?". That gate
originally probed 127.0.0.1 — but Beacon reaches these at $DR_MESH:<port> over
the mesh, so a loopback-only bind PASSED the gate while Beacon still got
`Connection refused`, and the flip proceeded anyway. That is exactly what
ADR-009 / decision #955 forbids ("pointing a hostname at a host that cannot
serve it is worse than leaving it pointed at one that is merely down"), and
DR_RUNBOOK.md already documents the identical trap for the standby platform:
"failover.sh's /login check only hits 127.0.0.1, so it passes while nodes still
can't reach it."

Same principle as task #5218 in this branch: measure on the path the traffic
actually uses, not the one that is convenient to measure.

The tests extract dr_service_listening() from the REAL failover.sh rather than
reimplementing it — sourcing failover.sh wholesale would execute a live
failover. 127.0.0.2 stands in for the mesh IP: it is a distinct bindable
address in 127.0.0.0/8, so "bound on the mesh IP" and "bound loopback-only"
are genuinely different states.
"""

import re
import socket
import subprocess
import textwrap
from pathlib import Path

import pytest
from tests.repo_root import repo_root

# The probe moved to beacon_flip.sh so all four DR scripts share ONE rule (#5225).
_MARKER = Path("scripts") / "dr" / "beacon_flip.sh"


def _find_repo():
    """Locate the repo root.

    Mirrors test_beacon_selective_flip.py: inside the container platform_v2 is
    mounted as /app and the repo root as /mnt/archie_brain, so a fixed parent
    depth does not hold.
    """
    for base in list(Path(__file__).resolve().parents) + [Path("/mnt/archie_brain")]:
        if (base / _MARKER).exists():
            return base
    return repo_root()


REPO = _find_repo()
HELPER = REPO / _MARKER

MESH = "127.0.0.2"  # stands in for $DR_MESH (100.64.0.10)
LOOPBACK = "127.0.0.1"

pytestmark = pytest.mark.skipif(not HELPER.exists(), reason="beacon_flip.sh not present in this checkout")


def _free_port():
    """A port free on BOTH addresses, so binding one proves nothing about the other."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOOPBACK, 0))
        port = probe.getsockname()[1]
    for addr in (LOOPBACK, MESH):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as check:
            try:
                check.bind((addr, port))
            except OSError:  # pragma: no cover - port raced
                pytest.skip(f"port {port} not free on {addr}")
    return port


class _Listener:
    """A socket listening on exactly one address — no accept loop needed:
    a completed TCP handshake from the listen backlog is what /dev/tcp tests."""

    def __init__(self, addr, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((addr, port))
        self.sock.listen(8)

    def close(self):
        self.sock.close()


def _run_probe(port, attempts=2):
    """Run the SHIPPED dr_service_listening() against `port`. -> (rc, output)."""
    src = HELPER.read_text()
    fn = re.search(r"^dr_service_listening\(\) \{.*?^\}", src, re.S | re.M)
    assert fn, "dr_service_listening() not found in beacon_flip.sh — did it move again?"

    driver = textwrap.dedent(
        f"""
        set -uo pipefail
        log() {{ echo "$*"; }}
        export DR_MESH="{MESH}"
        export DR_PROBE_ATTEMPTS={attempts}
        export DR_PROBE_INTERVAL=0
        {fn.group(0)}
        dr_service_listening "{MESH}" {port} "TestSvc"
        echo "RC=$?"
        """
    ).strip()

    proc = subprocess.run(["bash", "-c", driver], capture_output=True, text=True, timeout=60)
    out = proc.stdout + proc.stderr
    rc = int(re.search(r"RC=(\d+)", out).group(1))
    return rc, out


def test_service_bound_on_the_mesh_ip_is_accepted():
    """The happy path: Beacon could reach this, so the flip may proceed."""
    port = _free_port()
    listener = _Listener(MESH, port)
    try:
        rc, out = _run_probe(port)
    finally:
        listener.close()
    assert rc == 0, f"mesh-bound service should pass the gate:\n{out}"


def test_loopback_only_bind_is_refused():
    """THE REGRESSION. Bound on 127.0.0.1 but NOT on the mesh IP.

    The pre-fix probe hit 127.0.0.1 and returned success here, so failover.sh
    flipped mesh./creed. at a boston-2 that Beacon cannot reach.
    """
    port = _free_port()
    listener = _Listener(LOOPBACK, port)
    try:
        rc, out = _run_probe(port)
    finally:
        listener.close()
    assert rc != 0, (
        "a loopback-only bind must NOT satisfy the gate — Beacon reaches this "
        f"service over the mesh, not loopback:\n{out}"
    )


def test_loopback_only_bind_is_named_not_reported_as_generic_downtime():
    """The operator fix for 'bound wrong' differs from 'not running' — say which."""
    port = _free_port()
    listener = _Listener(LOOPBACK, port)
    try:
        _, out = _run_probe(port)
    finally:
        listener.close()
    assert "Loopback-only bind" in out, f"loopback trap not diagnosed:\n{out}"
    assert MESH in out, f"diagnostic should name the address Beacon uses:\n{out}"


def test_nothing_listening_is_refused_without_a_false_loopback_diagnosis():
    """A genuinely dead service must not be mislabelled as a binding problem."""
    port = _free_port()  # nothing bound at all
    rc, out = _run_probe(port)
    assert rc != 0, f"dead service must not pass the gate:\n{out}"
    assert "Loopback-only bind" not in out, f"false loopback diagnosis:\n{out}"
