"""Agent liveness vs node reachability — services/node_reachability.py (task #5218).

remote_nodes.status was wrong in BOTH directions inside one hour on 2026-07-26:
Starships read 'online' off LAN heartbeats while their MESH IPs were unreachable and
dispatch could not land; Beacon read 'offline' forever because it runs no node agent
by design and so can never send the signal it is judged by.

These pin the vocabulary that keeps the two questions apart.
"""

import socket
import threading

import pytest

from services.node_reachability import (
    DEFAULT_PROBE_PORTS,
    INGRESS_PROBE_PORTS,
    describe_status,
    heartbeat_is_meaningful,
    probe_node,
    probe_ports_for_role,
)


# --------------------------------------------------------------------------
# probe_node — measures the HOST, not Ollama
# --------------------------------------------------------------------------


@pytest.fixture
def listening_port():
    """A real listening TCP socket on localhost."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]

    stop = threading.Event()

    def _accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
                conn.close()
            except Exception:
                continue

    t = threading.Thread(target=_accept, daemon=True)
    t.start()
    yield port
    stop.set()
    t.join(timeout=2)
    srv.close()


def test_probe_reports_which_port_answered(listening_port):
    """A host is reachable if ANYTHING answers — and we record what did.

    The old probe connected only to :11434 and called the result 'mesh_status'.
    That is an inference-capability check wearing a reachability label.
    """
    result = probe_node("127.0.0.1", (listening_port,), timeout=2)
    assert result.reachable is True
    assert result.port == listening_port
    assert result.latency_ms is not None


def test_probe_falls_through_closed_ports_to_an_open_one(listening_port):
    """An ingress node answers on 443, not on the Ollama port.

    This is precisely Beacon: closed on 11434 (no Ollama by design), open on a
    web port. Probing only the first port declares it unreachable.
    """
    closed = _find_closed_port()
    result = probe_node("127.0.0.1", (closed, listening_port), timeout=2)
    assert result.reachable is True
    assert result.port == listening_port


def test_probe_unreachable_host_is_a_normal_result():
    closed = _find_closed_port()
    result = probe_node("127.0.0.1", (closed,), timeout=1)
    assert result == (False, None, None)


def test_probe_empty_host_never_raises():
    assert probe_node("", (80,)).reachable is False


def _find_closed_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --------------------------------------------------------------------------
# role-aware port selection
# --------------------------------------------------------------------------


def test_ingress_nodes_do_not_probe_the_inference_port():
    """Beacon runs no Ollama; probing it first just burns a timeout every cycle."""
    assert 11434 not in probe_ports_for_role("ingress")
    assert probe_ports_for_role("ingress") == INGRESS_PROBE_PORTS
    assert probe_ports_for_role("agent") == DEFAULT_PROBE_PORTS
    assert probe_ports_for_role(None) == DEFAULT_PROBE_PORTS


def test_heartbeat_is_meaningless_for_ingress_nodes():
    assert heartbeat_is_meaningful("agent") is True
    assert heartbeat_is_meaningful(None) is True
    assert heartbeat_is_meaningful("ingress") is False


# --------------------------------------------------------------------------
# describe_status — the two failure modes must not look healthy
# --------------------------------------------------------------------------


def test_lan_heartbeat_with_dead_mesh_is_not_online():
    """THE FALSE-ONLINE CASE.

    Both Starships showed green off 1-minute-old LAN heartbeats while their mesh
    IPs were unreachable and no dispatch could land. A node that cannot receive
    work must not render identically to one that can.
    """
    assert describe_status("agent", heartbeat_fresh=True, mesh_reachable=False) == "unreachable"


def test_reachable_host_with_dead_agent_is_distinguishable():
    assert describe_status("agent", heartbeat_fresh=False, mesh_reachable=True) == "agent_down"


def test_healthy_agent_node_is_online():
    assert describe_status("agent", heartbeat_fresh=True, mesh_reachable=True) == "online"


def test_fully_down_agent_node_is_offline():
    assert describe_status("agent", heartbeat_fresh=False, mesh_reachable=False) == "offline"


def test_ingress_node_is_judged_by_reachability_not_heartbeat():
    """THE FALSE-OFFLINE CASE.

    Beacon's heartbeat froze at a power-down and never resumed — it runs no node
    agent — yet it answered ping, showed online in headscale and served live
    public traffic the entire time. A stale heartbeat is not evidence about it.
    """
    assert describe_status("ingress", heartbeat_fresh=False, mesh_reachable=True) == "online"
    assert describe_status("ingress", heartbeat_fresh=None, mesh_reachable=True) == "online"
    assert describe_status("ingress", heartbeat_fresh=True, mesh_reachable=False) == "offline"


def test_unknown_signals_never_masquerade_as_healthy_or_dead():
    """Absence of evidence is not evidence of absence — the bug in one sentence.

    An earlier draft fell through to 'offline' when the mesh signal was merely
    UNKNOWN, which would have rendered every healthy node offline wherever the
    caller had not selected mesh_status.
    """
    assert describe_status("agent", None, None) == "unknown"
    assert describe_status("ingress", None, None) == "unknown"
    # One signal known: report it, do not invent the other.
    assert describe_status("agent", True, None) == "online"
    assert describe_status("agent", False, None) == "offline"
    assert describe_status("agent", None, True) == "online"
