"""Node reachability — "is this host answering on the mesh?" (task #5218).

WHY THIS IS SEPARATE FROM THE HEARTBEAT
---------------------------------------
The platform kept exactly one liveness signal per node, and it was derived
entirely from a node agent phoning home. On 2026-07-26 that was wrong in both
directions inside one hour:

  * Both Starships read ``status='online'`` off 1-minute-old heartbeats while
    their MESH IPs were unreachable and dispatch could not land. They heartbeat
    over the LAN; dispatch routes over the mesh. Nothing measured the path the
    traffic actually uses.

  * Beacon read ``status='offline'`` forever. It runs no node agent by design,
    so it can never send the signal it is judged by.

The pre-existing "mesh health" probe did not save us either, because it
TCP-connected to ``mesh_ip:11434`` — the **Ollama** port — and called the result
``mesh_status``. That is an inference-capability check wearing a reachability
label: Beacon deliberately runs no Ollama, so it failed the reachability probe
for the same structural reason it failed the heartbeat one.

This module measures REACHABILITY: does anything on that host accept a TCP
connection? It tries a small ordered set of ports and reports which one answered,
so "the host is up" and "Ollama is up" stay distinguishable instead of being
silently conflated.
"""

from __future__ import annotations

import logging
import socket
import time
from typing import Iterable, NamedTuple, Optional

logger = logging.getLogger(__name__)

# Ordered by how likely they are to answer FIRST across the fleet, cheapest first.
#   11434 Ollama  — agent nodes (also the legacy probe, kept first so agent nodes
#                   resolve in one connect and latency stays comparable to before)
#   3000  platform — the hub
#   443/80 Caddy   — ingress nodes (Beacon) and any node fronting HTTP
#   22    SSH      — near-universal fallback; a host with nothing else still answers
DEFAULT_PROBE_PORTS = (11434, 3000, 443, 80, 22)

# Ingress nodes serve traffic, not inference — probing Ollama first just burns a
# timeout on every cycle.
INGRESS_PROBE_PORTS = (443, 80, 22)

DEFAULT_TIMEOUT_S = 3.0


class Reachability(NamedTuple):
    """Result of a reachability probe.

    reachable  — something accepted a TCP connection.
    port       — which port answered (None when unreachable).
    latency_ms — connect time for the port that answered (None when unreachable).
    """

    reachable: bool
    port: Optional[int]
    latency_ms: Optional[int]


def probe_ports_for_role(node_role: Optional[str]) -> tuple:
    """Port set appropriate to what the node is FOR."""
    return INGRESS_PROBE_PORTS if (node_role or "agent") == "ingress" else DEFAULT_PROBE_PORTS


def probe_node(
    host: str,
    ports: Optional[Iterable[int]] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Reachability:
    """Return whether `host` accepts a TCP connection on any of `ports`.

    Stops at the first port that answers. Never raises — an unreachable host is
    a normal result, not an error.
    """
    if not host:
        return Reachability(False, None, None)

    for port in ports or DEFAULT_PROBE_PORTS:
        sock = None
        try:
            start = time.monotonic()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, int(port)))
            latency_ms = int((time.monotonic() - start) * 1000)
            return Reachability(True, int(port), latency_ms)
        except Exception:
            continue
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    return Reachability(False, None, None)


def heartbeat_is_meaningful(node_role: Optional[str]) -> bool:
    """Whether a missing heartbeat is EVIDENCE OF ANYTHING for this node.

    False for ingress nodes: they run no node agent, so a stale heartbeat says
    nothing about their health. Judging them by it produced a permanently
    'offline' Beacon that was serving live public traffic the whole time.
    """
    return (node_role or "agent") != "ingress"


def describe_status(
    node_role: Optional[str],
    heartbeat_fresh: Optional[bool],
    mesh_reachable: Optional[bool],
) -> str:
    """Combine the two signals into ONE honest label for the Fleet tab.

    The point of #5218 is that these are different questions, so a node that
    heartbeats but is unreachable over the mesh must NOT look identical to a
    healthy one — that is precisely how two GPU nodes showed green while unable
    to receive any work.

      online          agent alive AND mesh reachable (or ingress + reachable)
      unreachable     agent alive but the MESH path is dead — dispatch cannot land
      agent_down      mesh reachable but no recent heartbeat — host up, agent dead
      offline         neither
      unknown         not enough information to say (never assume healthy)
    """
    # Ingress: the heartbeat says nothing, so reachability is the whole story.
    if not heartbeat_is_meaningful(node_role):
        if mesh_reachable is None:
            return "unknown"
        return "online" if mesh_reachable else "offline"

    if heartbeat_fresh is None and mesh_reachable is None:
        return "unknown"

    # Exactly one signal available — report it rather than inventing the other.
    # (An earlier draft of this function fell through to 'offline' when the mesh
    # signal was merely UNKNOWN, which would have rendered every healthy node
    # offline wherever the caller did not select mesh_status. Absence of evidence
    # is not evidence of absence — that is the whole bug this task is about.)
    if mesh_reachable is None:
        return "online" if heartbeat_fresh else "offline"
    if heartbeat_fresh is None:
        return "online" if mesh_reachable else "offline"

    if heartbeat_fresh and mesh_reachable:
        return "online"
    if heartbeat_fresh and not mesh_reachable:
        return "unreachable"
    if not heartbeat_fresh and mesh_reachable:
        return "agent_down"
    return "offline"
