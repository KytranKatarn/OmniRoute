"""V.I.G.I.L. — Infrastructure Heartbeat Monitor.

Watches a curated set of critical infrastructure containers and
reports when one is stopped, removed, unhealthy, or unreachable.
Triggered by the 2026-04-18 NPM removal — nginx_proxy_manager was
silently ``docker rm``'d, none of the 23 Security Network agent-loop
jobs noticed, and the outage was only detected when a human tried to
hit a subdomain.

Complement to the existing Security Network module which owns NPM
*proxy host config* CRUD (creating/editing/deleting routes). This
service owns *container lifecycle* — is the container actually
running and reachable? — which was the gap the NPM outage exposed.

Callers
-------
1. MCP tool ``mcp__archie__check_infra_heartbeat`` — on demand.
2. Agent-loop job ``vigil_infra_heartbeat`` — every 5 min.
3. Recovery consumer — ``action_type='restart_container'`` in
   ``_execute_approved_action``. Tier 2 — Kytran approves each restart
   via Telegram. Can be promoted to Tier 1 auto-approve once the
   pattern is proven safe in prod.

Checked signals per container
-----------------------------
* **Present** — ``docker inspect`` finds it at all (catches ``docker
  rm`` removals — the NPM failure mode).
* **Running** — state is ``running`` (catches stopped).
* **Healthy** — if a healthcheck is defined, its last status.
* **Reachable** — TCP probes + optional HTTP probe confirm the port
  is actually answering (catches "running but broken").

Failure reason is surfaced verbatim so the Telegram alert tells you
whether to approve a restart or investigate deeper.

Scope note
----------
``archie_platform`` is deliberately NOT in the critical set — this
service runs *inside* that container and cannot observe its own
liveness. The platform's ``restart: unless-stopped`` policy and
Kytran's own usage catch archie_platform outages quickly.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry of critical containers + their probes.
# Keep this in sync with docker-compose.yml. Non-critical sidecars
# (security_nmap, security_nikto, dev helpers) are intentionally absent.
# ---------------------------------------------------------------------------

CRITICAL_CONTAINERS: Dict[str, Dict[str, Any]] = {
    "nginx_proxy_manager": {
        "description": "NPM reverse proxy — gates all *.kytranempowerment.com subdomains",
        "tcp_probes": [80, 443],
        "http_probe": "http://nginx_proxy_manager:81/api",
        "auto_restart_safe": True,
        "compose_service": "nginx_proxy_manager",
    },
    "network_adguard": {
        "description": "AdGuard DNS — internal resolution + ad blocking",
        "tcp_probes": [53],
        "auto_restart_safe": True,
        "compose_service": "network_adguard",
    },
    "archie_comms": {
        "description": "A.R.C.H.I.E. voice + Telegram bridge (port 3002)",
        "tcp_probes": [3002],
        "auto_restart_safe": True,
        "compose_service": "archie_comms",
    },
    "archie_comfyui": {
        "description": "ComfyUI image generation service (port 8188) — on-demand",
        "tcp_probes": [8188],
        "auto_restart_safe": True,
        "compose_service": "archie_comfyui",
        # On-demand: container is only running during SDXL generation
        # (VRAM swap with Ollama). An 'exited' state is the normal idle
        # state, not a failure. Dispatcher spins it up when Pixel needs it.
        "service_class": "on-demand",
    },
    "kbs_app": {
        "description": "Kytran Business Suite (port 8091)",
        "tcp_probes": [8091],
        "auto_restart_safe": True,
        "compose_service": "kbs_app",
    },
    "kytran-system-operations": {
        "description": "KSO compliance engine (port 8085)",
        "tcp_probes": [8085],
        "auto_restart_safe": True,
        "compose_service": "kytran-system-operations",
    },
    "kytran_creed": {
        "description": "C.R.E.E.D. governance (port 8086)",
        "tcp_probes": [8086],
        "auto_restart_safe": True,
        "compose_service": "kytran_creed",
    },
    "media_plex": {
        "description": "Plex media server",
        "tcp_probes": [32400],
        "auto_restart_safe": True,
        "compose_service": "media_plex",
    },
    "media_jellyfin": {
        "description": "Jellyfin media server",
        "tcp_probes": [8096],
        "auto_restart_safe": True,
        "compose_service": "media_jellyfin",
    },
}

# Hub IP — probes run from inside the archie_platform container, but
# ports are bound on the host. Use the docker bridge gateway to reach
# host-bound ports from inside.
_PROBE_HOST_FROM_CONTAINER = os.getenv("HUB_IP", "192.168.1.200")
_PROBE_TIMEOUT_SECONDS = 3


# ---------------------------------------------------------------------------
# Probes — small, self-contained, no third-party deps beyond stdlib.
# ---------------------------------------------------------------------------


def _tcp_probe(host: str, port: int, timeout: float = _PROBE_TIMEOUT_SECONDS) -> bool:
    """Return True if a TCP connect succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _http_probe(url: str, timeout: float = _PROBE_TIMEOUT_SECONDS) -> Optional[int]:
    """Return HTTP status code or None on connection failure."""
    try:
        req = urllib_request.Request(url, method="GET")
        with urllib_request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            return resp.status
    except urllib_error.HTTPError as e:
        # 4xx/5xx is a real HTTP response — the container IS answering.
        return e.code
    except (urllib_error.URLError, socket.timeout, ConnectionError):
        return None


# ---------------------------------------------------------------------------
# Docker introspection — prefer the docker SDK, fall back to CLI.
# ---------------------------------------------------------------------------


def _inspect_via_sdk(name: str) -> Optional[Dict[str, Any]]:
    """Return {'present', 'state', 'health'} or None on failure."""
    try:
        import docker  # type: ignore

        client = docker.from_env()
        container = client.containers.get(name)
        state = container.attrs.get("State", {})
        health = (state.get("Health") or {}).get("Status") if state.get("Health") else None
        return {
            "present": True,
            "state": state.get("Status"),  # running, exited, paused, etc.
            "health": health,
            "started_at": state.get("StartedAt"),
        }
    except ImportError:
        return None
    except Exception as e:
        # NotFound raised if container doesn't exist
        if "NotFound" in type(e).__name__ or "not found" in str(e).lower():
            return {"present": False, "state": None, "health": None, "started_at": None}
        logger.warning("docker SDK inspect failed for %s: %s", name, e)
        return None


def _inspect_via_cli(name: str) -> Optional[Dict[str, Any]]:
    """Fallback: shell out to docker CLI."""
    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.StartedAt}}",
                name,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        # Not found
        return {"present": False, "state": None, "health": None, "started_at": None}
    parts = result.stdout.strip().split("|")
    state = parts[0] if parts else None
    health = parts[1] if len(parts) > 1 and parts[1] != "none" else None
    started = parts[2] if len(parts) > 2 else None
    return {
        "present": True,
        "state": state,
        "health": health,
        "started_at": started,
    }


def inspect_container(name: str) -> Dict[str, Any]:
    """Return a uniform snapshot of a container's state.

    Keys: ``present`` (bool), ``state`` (str|None),
    ``health`` (str|None), ``started_at`` (str|None).
    """
    snap = _inspect_via_sdk(name)
    if snap is not None:
        return snap
    snap = _inspect_via_cli(name)
    if snap is not None:
        return snap
    return {"present": False, "state": None, "health": None, "started_at": None}


# ---------------------------------------------------------------------------
# Per-container health evaluation
# ---------------------------------------------------------------------------


def check_container(name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate one container. Returns a structured record the job + MCP
    tool both render.

    ``severity`` rollup per container:
      * ``error``   — container absent or exited
      * ``warning`` — container running but port/http probe fails
      * ``info``    — all probes pass
    """
    snap = inspect_container(name)
    service_class = config.get("service_class", "always-on")
    result: Dict[str, Any] = {
        "name": name,
        "description": config.get("description"),
        **snap,
        "tcp_probes": {},
        "http_probe": None,
        "auto_restart_safe": bool(config.get("auto_restart_safe")),
        "compose_service": config.get("compose_service", name),
        "service_class": service_class,
    }

    # Escalate immediately if the container isn't present or running.
    if not snap["present"]:
        # On-demand services may be absent at rest (e.g., scale=0 sidecars).
        # Treat as info rather than error — dispatcher will spin them up.
        if service_class == "on-demand":
            result["severity"] = "info"
            result["reason"] = "on-demand — not currently running (normal at rest)"
            return result
        result["severity"] = "error"
        result["reason"] = "container absent from docker (likely removed)"
        return result
    if snap["state"] != "running":
        # On-demand services spend most of their time exited — that IS the
        # normal idle state, not a failure. Dispatcher brings them up when
        # Pixel/SDXL needs them. Surface as info so V.I.G.I.L. still reports
        # state but doesn't page A.R.C.H.I.E. about it.
        if service_class == "on-demand" and snap["state"] == "exited":
            result["severity"] = "info"
            result["reason"] = "idle (on-demand; dispatcher spins up when needed)"
            return result
        # Any other non-running state for on-demand (restarting, dead, paused,
        # created) still warrants a warning — not expected idle behavior.
        severity = "warning" if service_class == "on-demand" else "error"
        result["severity"] = severity
        result["reason"] = f"container state={snap['state']!r}"
        return result

    # Healthy-but-unreachable cases — run the reachability probes.
    failed: List[str] = []
    for port in config.get("tcp_probes", []):
        ok = _tcp_probe(_PROBE_HOST_FROM_CONTAINER, port)
        result["tcp_probes"][port] = ok
        if not ok:
            failed.append(f"tcp:{port}")

    http_url = config.get("http_probe")
    if http_url:
        code = _http_probe(http_url)
        result["http_probe"] = code
        # 5xx or None is a failure. 2xx/3xx/4xx still means it's
        # *responding*, which is what we care about at this layer.
        if code is None or code >= 500:
            failed.append(f"GET {http_url}")

    if failed:
        result["severity"] = "warning"
        result["reason"] = f"probes failed: {', '.join(failed)}"
    else:
        result["severity"] = "info"
        result["reason"] = "all probes passed"
        if snap["health"] and snap["health"] != "healthy":
            result["severity"] = "warning"
            result["reason"] = f"docker health status={snap['health']!r}"

    return result


# ---------------------------------------------------------------------------
# Forensics — recent docker events for a given container
# ---------------------------------------------------------------------------


def get_recent_events(name: str, since_hours: int = 24) -> List[str]:
    """Return short event log lines for a container, newest first.

    Best-effort — returns empty list if docker events is unavailable
    or the query fails. Used to give the alert a clue about *when*
    something changed.
    """
    try:
        result = subprocess.run(
            [
                "docker",
                "events",
                "--since",
                f"{since_hours}h",
                "--until",
                "0s",
                "--filter",
                f"container={name}",
                "--format",
                "{{.Time}} {{.Action}} {{.Actor.Attributes.name}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return []
    lines = [ln for ln in result.stdout.strip().splitlines() if ln]
    return lines[-20:][::-1]  # newest last in stream → reverse to get newest first


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def check_all_critical() -> Dict[str, Any]:
    """Run the full heartbeat pass over every registered critical container.

    Returns a structured payload for both the MCP tool and the agent-loop
    job. Does not mutate anything — logging + approval submission happen
    in the caller.
    """
    ran_at = datetime.now(timezone.utc).isoformat()
    per_container: List[Dict[str, Any]] = []
    down_names: List[str] = []
    warning_names: List[str] = []

    for name, config in CRITICAL_CONTAINERS.items():
        record = check_container(name, config)
        if record["severity"] == "error":
            # Attach forensics only when actionable — saves spam.
            record["recent_events"] = get_recent_events(name)
            down_names.append(name)
        elif record["severity"] == "warning":
            warning_names.append(name)
        per_container.append(record)

    severity = "info"
    reasons: List[str] = []
    if down_names:
        severity = "error"
        reasons.append(f"{len(down_names)} container(s) DOWN: {', '.join(down_names)}")
    if warning_names:
        if severity != "error":
            severity = "warning"
        reasons.append(f"{len(warning_names)} container(s) with probe warnings")

    return {
        "ran_at": ran_at,
        "checked_count": len(CRITICAL_CONTAINERS),
        "containers": per_container,
        "down_names": down_names,
        "warning_names": warning_names,
        "severity": severity,
        "reasons": reasons,
        "summary_metrics": {
            "total": len(CRITICAL_CONTAINERS),
            "down": len(down_names),
            "warnings": len(warning_names),
            "healthy": len(CRITICAL_CONTAINERS) - len(down_names) - len(warning_names),
        },
    }


# ---------------------------------------------------------------------------
# Recovery — invoked ONLY by the approval consumer, never directly.
# ---------------------------------------------------------------------------


def restart_container(compose_service: str, reason: str = "approved restart") -> Dict[str, Any]:
    """Bring a critical container back up via compose.

    ``--no-deps`` ensures we don't accidentally recreate siblings that
    happen to have pending config drift. Called only after an
    ``action_type='restart_container'`` approval is granted.
    """
    if compose_service not in {c.get("compose_service", k) for k, c in CRITICAL_CONTAINERS.items()}:
        return {
            "success": False,
            "error": f"{compose_service!r} is not in the critical container registry",
        }
    try:
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "--no-deps", compose_service],
            capture_output=True,
            text=True,
            timeout=90,
            cwd="/mnt/archie_brain",
        )
    except Exception as e:
        logger.error("restart_container(%s) subprocess failed: %s", compose_service, e)
        return {"success": False, "error": str(e)}
    if result.returncode != 0:
        return {
            "success": False,
            "error": f"docker compose exit {result.returncode}: {result.stderr.strip()[:300]}",
            "stdout": result.stdout.strip()[:300],
        }
    logger.info("[infra_heartbeat] Restarted %s: %s", compose_service, reason)
    return {
        "success": True,
        "compose_service": compose_service,
        "reason": reason,
        "stdout": result.stdout.strip()[:300],
    }


# ---------------------------------------------------------------------------
# Alert formatter
# ---------------------------------------------------------------------------


def format_alert_message(result: Dict[str, Any]) -> str:
    """Compact message for Telegram / system_notifications."""
    metrics = result["summary_metrics"]
    lines = [
        "V.I.G.I.L. — infra heartbeat",
        f"Severity: *{result['severity'].upper()}* · "
        f"{metrics['down']} down · {metrics['warnings']} warning · "
        f"{metrics['healthy']} healthy ({metrics['total']} watched)",
    ]
    if result["down_names"]:
        lines.append("")
        lines.append("DOWN:")
        for record in result["containers"]:
            if record["severity"] == "error":
                lines.append(f"  – {record['name']}: {record['reason']}")
                events = record.get("recent_events") or []
                if events:
                    lines.append(f"    last events: {events[0][:100]}")
    if result["warning_names"]:
        lines.append("")
        lines.append("Warnings:")
        for record in result["containers"]:
            if record["severity"] == "warning":
                lines.append(f"  – {record['name']}: {record['reason']}")
    return "\n".join(lines)
