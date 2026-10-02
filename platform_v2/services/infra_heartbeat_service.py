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


class DockerObserverUnavailable(RuntimeError):
    """The check could not SEE docker at all.

    This is the single most important distinction in this module, and getting it
    wrong is worse than having no monitor at all.

    ``docker inspect`` exits non-zero for two unrelated things: "No such object"
    (the container is genuinely gone) and "Cannot connect to the Docker daemon"
    (the observer is blind). Collapsing the second into the first makes a blind
    observer manufacture an outage — every registered container reported as
    "absent from docker (likely removed)", at ``severity: error``, with
    ``auto_restart_safe`` set on most of them.

    That is not hypothetical. ``archie_mcp_gateway`` deliberately runs WITHOUT a
    docker socket (read-only DB role, no host access — see mcp-gateway/gateway.py),
    and it serves the READ tools in-process. So every MCP caller — both coder lanes
    and any agent using this tool — got a fabricated 9-of-10-down emergency for a
    fully healthy hub. Verified against the running containers: all 42 up.

    So: absence is a claim about a container. Blindness is a claim about the
    observer. Only the first may raise an alert or file a restart approval.
    """


# Substrings that mean "the docker daemon is unreachable", as opposed to
# "no such container". Checked against CLI stderr and SDK exception text.
_DAEMON_UNREACHABLE_MARKERS = (
    "cannot connect to the docker daemon",
    "is the docker daemon running",
    "error during connect",
    "permission denied while trying to connect to the docker daemon",
    "could not connect to docker",
)


def _looks_like_daemon_unreachable(text: str) -> bool:
    """True when docker's own error text means 'I cannot see', not 'it is gone'."""
    low = (text or "").lower()
    return any(marker in low for marker in _DAEMON_UNREACHABLE_MARKERS)


# ---------------------------------------------------------------------------
# Registry of critical containers + their probes.
# Keep this in sync with the compose files named below.
#
# `compose_file` is NOT decoration. restart_container() shells out to
# `docker compose -f <compose_file> up -d --no-deps <compose_service>`, and
# `docker compose` with no -f only ever reads the compose file in its cwd
# (/mnt/archie_brain/docker-compose.yml). Six of the ten original entries name
# a service that does not exist in that file — media_plex's real service is
# `plex` in media-stack/docker-compose.yml, kbs_app's is
# `kytran-business-suite` in kytran-business-suite/docker-compose.yml, and so
# on. Those restarts were therefore guaranteed to fail with "no such service"
# (verified: `docker compose up --dry-run` for each). An approval that cannot
# execute is worse than no approval: it spends a human's attention on a
# recovery that does not happen. test_registry_compose_wiring_exists() now
# fails if an entry names a service missing from its own compose file.
#
# `auto_restart_safe` means "compose-up of this entry would actually bring it
# back, and doing so unattended is safe". It is NOT a statement about
# importance — plenty of important containers are detection-only. A false
# positive that files a restart for a mesh component or a stateful database is
# worse than the alert it was trying to shorten.
#
# Two tiers, on purpose:
#   tier 1  hub spine — everything else's failure traces back to one of these
#   tier 2  data stores, media, mail, and the monitoring stack itself
#
# Deliberately NOT watched (presence is not a health signal for these):
#   archie_opencode_terminal*, archie_codex_terminal — dev lanes; a lane with
#     no active session is *supposed* to be down. An "absent" alert per lane
#     would be noise on every restart, and reviving an idle lane is not a
#     recovery.
#   archie_browser, archie_browser_login, archie_scraper — interactive
#     tooling, driven on demand.
#   archie_staging, archie_staging_db — the sandbox (see the sandbox-work
#     skill); its lifecycle is deliberate, not an incident.
#   security_nmap/nikto/nuclei/testssl/zap — scanner fleet. Separate finding:
#     security_zap's healthcheck curls `/`, which ZAP answers non-2xx, so it
#     has been `unhealthy` continuously while serving fine. Watching it as-is
#     would manufacture a permanent false alarm. Not added until its
#     healthcheck is corrected.
# ---------------------------------------------------------------------------

_HUB_COMPOSE = "/mnt/archie_brain/docker-compose.yml"
_MEDIA_COMPOSE = "/mnt/archie_brain/media-stack/docker-compose.yml"
_KBS_COMPOSE = "/mnt/archie_brain/kytran-business-suite/docker-compose.yml"
_NETTOOLS_COMPOSE = "/mnt/archie_brain/network-tools/docker-compose.yml"
_SYSOPS_COMPOSE = "/mnt/archie_brain/kytran-server-manager/docker-compose.yml"
_CREED_COMPOSE = "/mnt/archie_brain/kytran-creed/docker-compose.yml"
_MEDIAHUB_COMPOSE = "/mnt/archie_brain/standalone/media_hub/docker-compose.yml"
_TDARR_COMPOSE = "/mnt/archie_brain/standalone/tdarr/docker-compose.yml"
_MAIL_COMPOSE = "/mnt/archie_brain/stalwart-mail/docker-compose.yml"
# cadvisor/dozzle/nagios are NOT in network-tools/docker-compose.yml — they run
# from a separate stack at /mnt/stacks/network-tools.
_MONITORING_COMPOSE = "/mnt/stacks/network-tools/docker-compose.yml"

CRITICAL_CONTAINERS: Dict[str, Dict[str, Any]] = {
    # nginx_proxy_manager removed 2026-06-27 — NPM decommissioned, replaced by Beacon
    # (2.25.170.252) as the sole hub front door (ADR-851, KB #276140). It is no longer
    # critical infra and was removed from docker-compose.yml (PR #1953). Watching it here
    # re-fired a restart_container approval every time it was stopped (the revival loop),
    # and the restart command (`docker compose up -d nginx_proxy_manager`) now errors since
    # the service is gone. Do NOT re-add.
    #
    # === TIER 1 — HUB SPINE ===
    "archie_database": {
        "description": "PostgreSQL — the hub's primary datastore (every module reads it)",
        "tcp_probes": [5432],
        "auto_restart_safe": True,
        "compose_service": "archie_database",
        "compose_file": _HUB_COMPOSE,
        "tier": 1,
        # Detection + recovery only. NOT a probe-only entry: a hub with no
        # database is down for every module, and this is the single most
        # load-bearing process on the box.
    },
    "archie_platform": {
        "description": "A.R.C.H.I.E. hub — Flask API + UI (port 3000)",
        "tcp_probes": [3000],
        "auto_restart_safe": True,
        "compose_service": "archie_platform",
        "compose_file": _HUB_COMPOSE,
        "tier": 1,
    },
    "archie_scheduler": {
        "description": "Agent loop / cron runner — the process V.I.G.I.L. itself runs in",
        # No tcp_probe on purpose. archie_scheduler publishes nothing; the only
        # thing on 192.168.1.200:3000 is archie_platform. Probing it would test
        # the platform and report a green light for the scheduler — the exact
        # "looks monitored, isn't" shape #5409 was filed for. The container's own
        # healthcheck (a real psycopg2 connect) is the honest signal.
        "tcp_probes": [],
        "auto_restart_safe": True,
        "compose_service": "archie_scheduler",
        "compose_file": _HUB_COMPOSE,
        "tier": 1,
    },
    "archie_mcp_gateway": {
        "description": "MCP stdio/HTTP gateway — the surface the observer-blindness fix (#3570) exists for",
        # No tcp_probe: 7800 is bound to 127.0.0.1 only, unreachable from the
        # probe host. Healthcheck is authoritative.
        "tcp_probes": [],
        "auto_restart_safe": True,
        "compose_service": "archie_mcp_gateway",
        "compose_file": _HUB_COMPOSE,
        "tier": 1,
    },
    "archie_engine": {
        "description": "Orchestration engine (ws 9090)",
        # 9090 is bound to 127.0.0.1; healthcheck covers it.
        "tcp_probes": [],
        "auto_restart_safe": True,
        "compose_service": "archie_engine",
        "compose_file": _HUB_COMPOSE,
        "tier": 1,
    },
    "archie_ollama": {
        "description": "Ollama inference — all local LLM capacity",
        "tcp_probes": [],
        "auto_restart_safe": True,
        "compose_service": "archie_ollama",
        "compose_file": _HUB_COMPOSE,
        "tier": 1,
    },
    "archie_headscale": {
        "description": "Headscale control plane — the mesh every inter-service call runs on",
        "tcp_probes": [8095],
        "auto_restart_safe": True,
        "compose_service": "archie_headscale",
        "compose_file": _HUB_COMPOSE,
        "tier": 1,
    },
    "archie_comms": {
        "description": "A.R.C.H.I.E. voice + Telegram bridge (port 3002)",
        "tcp_probes": [3002],
        "auto_restart_safe": True,
        "compose_service": "archie_comms",
        "compose_file": _HUB_COMPOSE,
        "tier": 1,
    },
    "archie_hub_caddy": {
        "description": "Caddy — the hub's front door (TLS, reverse proxy)",
        # :80, verified — NOT :3001. Caddy runs in the host network namespace
        # (`auto_https off`, no certs obtainable while inbound :80 is broken).
        # 3001 looks like an obvious candidate on a host-mode container and is a
        # trap: `ss` inside any host-mode container reports the WHOLE host
        # namespace, so ntopng's listener appears to belong to Caddy. It does
        # not — ntopng runs `-w 3001`. Probing 3001 here would have gone green
        # while Caddy was dead.
        "tcp_probes": [80],
        # Bare `docker run`, no compose project (labels confirm). Detection
        # only: there is no compose file to name, so restart is impossible.
        "auto_restart_safe": False,
        "compose_service": "archie_hub_caddy",
        "compose_file": None,
        "tier": 1,
    },
    "archie_tailscale": {
        "description": "Hub-LAN subnet router (mesh presence 100.64.0.1) — dormant but must stay registered",
        "tcp_probes": [],
        # Detection only. Restarting a mesh component on a false positive is
        # worse than the alert, and this one has extra_hosts subtleties
        # (`docker compose restart` does NOT reapply them — see .claude/rules/fleet.md).
        "auto_restart_safe": False,
        "compose_service": "archie_tailscale",
        "compose_file": _HUB_COMPOSE,
        "tier": 1,
    },
    "network_adguard": {
        "description": "AdGuard DNS — internal resolution + ad blocking",
        "tcp_probes": [53],
        "auto_restart_safe": True,
        "compose_service": "network_adguard",
        "compose_file": _NETTOOLS_COMPOSE,
        "tier": 1,
    },
    "kytran-system-operations": {
        "description": "KSO compliance engine (port 8085)",
        "tcp_probes": [8085],
        "auto_restart_safe": True,
        "compose_service": "kytran-system-operations",
        "compose_file": _SYSOPS_COMPOSE,
        "tier": 1,
    },
    "kytran_creed": {
        "description": "C.R.E.E.D. governance (port 8086)",
        "tcp_probes": [8086],
        "auto_restart_safe": True,
        # The service is `creed`, not `kytran_creed`. The container name and the
        # compose service name differ for this one.
        "compose_service": "creed",
        "compose_file": _CREED_COMPOSE,
        "tier": 1,
    },
    "kbs_app": {
        "description": "Kytran Business Suite (port 8091)",
        "tcp_probes": [8091],
        "auto_restart_safe": True,
        # service name is `kytran-business-suite`, container name is `kbs_app`.
        "compose_service": "kytran-business-suite",
        "compose_file": _KBS_COMPOSE,
        "tier": 1,
    },
    # === TIER 2 — DATA STORES ===
    "kbs_postgres": {
        "description": "PostgreSQL — KBS datastore",
        # No healthcheck on this container, and 5432 is unpublished. Probing
        # the probe host's 5432 would test archie_database instead — a green
        # light for the wrong database. Verified from inside the observer:
        # both the compose DNS name and the container IP (172.28.0.3) time out,
        # because the observer shares no network with kytran-business-suite_default.
        "tcp_probes": [],
        "presence_only_reason": (
            "no healthcheck; isolated on kytran-business-suite_default, unreachable "
            "from the observer by name or IP. Detects ABSENCE only — a wedged "
            "postmaster still reports healthy. Fix by adding a healthcheck to the "
            "kbs-postgres service, then drop this field."
        ),
        "auto_restart_safe": True,
        "compose_service": "kbs-postgres",
        "compose_file": _KBS_COMPOSE,
        "tier": 2,
    },
    "kbs_redis": {
        "description": "Redis — KBS job queues + cache",
        # Same isolation as kbs_postgres: no healthcheck, no published port, and
        # the observer cannot route to 172.28.0.2.
        "tcp_probes": [],
        "presence_only_reason": (
            "no healthcheck; isolated on kytran-business-suite_default, unreachable "
            "from the observer. Detects ABSENCE only. Add a redis-cli PING "
            "healthcheck to the kbs-redis service to close this."
        ),
        "auto_restart_safe": True,
        "compose_service": "kbs-redis",
        "compose_file": _KBS_COMPOSE,
        "tier": 2,
    },
    "creed_postgres": {
        "description": "PostgreSQL — C.R.E.E.D. datastore",
        "tcp_probes": [],
        "auto_restart_safe": True,
        "compose_service": "postgres",
        "compose_file": _CREED_COMPOSE,
        "tier": 2,
    },
    "kytran-sysops-postgres": {
        "description": "PostgreSQL — KSO datastore",
        "tcp_probes": [],
        "auto_restart_safe": True,
        "compose_service": "postgres",
        "compose_file": _SYSOPS_COMPOSE,
        "tier": 2,
    },
    "mediahub_db": {
        "description": "PostgreSQL — media hub datastore",
        "tcp_probes": [],
        "auto_restart_safe": True,
        "compose_service": "mediahub_db",
        "compose_file": _MEDIAHUB_COMPOSE,
        "tier": 2,
    },
    "network_redis": {
        "description": "Redis — network-tools shared state",
        # Publishes 6379 to 127.0.0.1 ONLY (verified: `docker port` shows
        # 127.0.0.1:6379, and a connect from the observer to 192.168.1.200:6379
        # is refused). So the port cannot be probed from the observer, and no
        # healthcheck is defined.
        "tcp_probes": [],
        "presence_only_reason": (
            "no healthcheck; publishes to 127.0.0.1 only, refused from the probe "
            "host. Detects ABSENCE only. Add a redis-cli PING healthcheck."
        ),
        "auto_restart_safe": True,
        "compose_service": "network_redis",
        "compose_file": _NETTOOLS_COMPOSE,
        "tier": 2,
    },
    # === TIER 2 — MEDIA ===
    # All of these name a compose service in media-stack/docker-compose.yml.
    "media_plex": {
        "description": "Plex media server",
        "tcp_probes": [32400],
        "auto_restart_safe": True,
        "compose_service": "plex",
        "compose_file": _MEDIA_COMPOSE,
        "tier": 2,
    },
    "media_jellyfin": {
        "description": "Jellyfin media server",
        "tcp_probes": [8096],
        "auto_restart_safe": True,
        "compose_service": "jellyfin",
        "compose_file": _MEDIA_COMPOSE,
        "tier": 2,
    },
    "media_radarr": {
        "description": "Radarr — movie library automation (port 7878)",
        "tcp_probes": [7878],
        "auto_restart_safe": True,
        "compose_service": "radarr",
        "compose_file": _MEDIA_COMPOSE,
        "tier": 2,
    },
    "media_sonarr": {
        "description": "Sonarr — TV library automation (port 8989)",
        "tcp_probes": [8989],
        "auto_restart_safe": True,
        "compose_service": "sonarr",
        "compose_file": _MEDIA_COMPOSE,
        "tier": 2,
    },
    "media_prowlarr": {
        "description": "Prowlarr — indexer manager (port 9696)",
        "tcp_probes": [9696],
        "auto_restart_safe": True,
        "compose_service": "prowlarr",
        "compose_file": _MEDIA_COMPOSE,
        "tier": 2,
    },
    "media_sabnzbd": {
        "description": "SABnzbd — usenet downloader (host 8083 → container 8080)",
        "tcp_probes": [8083],
        "auto_restart_safe": True,
        "compose_service": "sabnzbd",
        "compose_file": _MEDIA_COMPOSE,
        "tier": 2,
    },
    "media_overseerr": {
        "description": "Overseerr — media request portal (port 5055)",
        "tcp_probes": [5055],
        "auto_restart_safe": True,
        "compose_service": "overseerr",
        "compose_file": _MEDIA_COMPOSE,
        "tier": 2,
    },
    "media_samba": {
        "description": "SMB export of /media — Tdarr fleet nodes mount the library over it",
        "tcp_probes": [],
        # NOT restart-safe: this entry is keyed on `docker-compose.samba.yml`,
        # a separate file, and the approval path would otherwise compose-up the
        # wrong stack. Detection only until that is wired.
        # Also no tcp_probe: media_samba publishes on 100.64.0.4:445, so probing
        # _PROBE_HOST_FROM_CONTAINER (192.168.1.200) would report a false
        # failure. Its docker healthcheck is the honest signal — media_samba's
        # had a FailingStreak of 3014 while nothing was watching it.
        "auto_restart_safe": False,
        "compose_service": "samba",
        "compose_file": "/mnt/archie_brain/media-stack/docker-compose.samba.yml",
        "tier": 2,
    },
    "mediahub_app": {
        "description": "Media hub app (port 8105)",
        "tcp_probes": [8105],
        "auto_restart_safe": True,
        "compose_service": "mediahub_app",
        "compose_file": _MEDIAHUB_COMPOSE,
        "tier": 2,
    },
    "tdarr": {
        "description": "Tdarr — distributed transcode worker (port 8265)",
        "tcp_probes": [8265],
        "auto_restart_safe": True,
        "compose_service": "tdarr",
        "compose_file": _TDARR_COMPOSE,
        "tier": 2,
    },
    # === TIER 2 — MAIL ===
    "stalwart_mail": {
        "description": "Stalwart — inbound/outbound mail (SMTP 25/587, IMAP 993)",
        # 25/465/587/993 all verified reachable from the probe host. Probing
        # only 25: a listener that binds SMTP but has lost IMAP is a real,
        # distinct outage, and one probe would call it healthy.
        "tcp_probes": [25, 587, 993],
        "auto_restart_safe": True,
        "compose_service": "stalwart-mail",
        "compose_file": _MAIL_COMPOSE,
        "tier": 2,
    },
    # === TIER 2 — THE MONITORING STACK ===
    # If these are down, V.I.G.I.L. is the only thing still reporting — and
    # nothing is watching V.I.G.I.L. itself. See _monitoring_redundancy_health.
    "monitoring_cadvisor": {
        "description": "cAdvisor — container metrics (port 8081)",
        "tcp_probes": [8081],
        "auto_restart_safe": True,
        "compose_service": "cadvisor",
        "compose_file": _MONITORING_COMPOSE,
        "tier": 2,
    },
    "monitoring_dozzle": {
        "description": "Dozzle — container log viewer (port 8080)",
        "tcp_probes": [8080],
        "auto_restart_safe": True,
        "compose_service": "dozzle",
        "compose_file": _MONITORING_COMPOSE,
        "tier": 2,
    },
    "monitoring_nagios": {
        "description": "Nagios — host/service checks (port 8082)",
        "tcp_probes": [8082],
        # No restart even though the compose wiring is known: this is the
        # system's redundancy for V.I.G.I.L. itself, so a false positive here
        # is the one most likely to be approved on autopilot. Detection first.
        "auto_restart_safe": False,
        "compose_service": "nagios",
        "compose_file": _MONITORING_COMPOSE,
        "tier": 2,
    },
    "network_ntopng": {
        "description": "ntopng — flow analysis (host mode, web UI :3001)",
        # 3001 IS ntopng — from its own argv: `ntopng --redis 127.0.0.1:6379
        # -i eno1 -w 3001`. Verified reachable from the probe host. Watch the
        # sibling entry archie_hub_caddy before "fixing" a port here.
        "tcp_probes": [3001],
        "auto_restart_safe": True,
        "compose_service": "network_ntopng",
        "compose_file": _NETTOOLS_COMPOSE,
        "tier": 2,
    },
    "archie_comfyui": {
        "description": "ComfyUI image generation service (port 8188) — on-demand",
        "tcp_probes": [8188],
        "auto_restart_safe": True,
        "compose_service": "archie_comfyui",
        "compose_file": _HUB_COMPOSE,
        # On-demand: container is only running during SDXL generation
        # (VRAM swap with Ollama). Exited = normal idle — P.I.X.E.L. wakes it
        # via media_generation_worker before claiming any pending job.
        "service_class": "on-demand",
        "tier": 2,
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


def _absent_snapshot() -> Dict[str, Any]:
    """Uniform "this container does not exist" snapshot.

    One helper rather than three literals: when the same dict was spelled out at
    each call site it was easy to add a key to one and miss the others, leaving a
    check reading ``None`` for the very field it depends on.
    """
    return {
        "present": False,
        "state": None,
        "health": None,
        "started_at": None,
        "networks": [],
        "network_mode": None,
    }


def _inspect_via_sdk(name: str) -> Optional[Dict[str, Any]]:
    """Return a snapshot dict (see :func:`inspect_container`) or None on failure.

    Raises :class:`DockerObserverUnavailable` when the SDK is present but cannot
    reach the daemon — that is blindness, not absence (see that class).
    """
    try:
        import docker  # type: ignore

        client = docker.from_env()
        container = client.containers.get(name)
        state = container.attrs.get("State", {})
        health = (state.get("Health") or {}).get("Status") if state.get("Health") else None
        net_settings = container.attrs.get("NetworkSettings") or {}
        host_config = container.attrs.get("HostConfig") or {}
        return {
            "present": True,
            "state": state.get("Status"),  # running, exited, paused, etc.
            "health": health,
            "started_at": state.get("StartedAt"),
            "networks": sorted((net_settings.get("Networks") or {}).keys()),
            "network_mode": host_config.get("NetworkMode"),
        }
    except ImportError:
        return None
    except Exception as e:
        # NotFound raised if container doesn't exist. Checked FIRST because
        # docker.errors.NotFound subclasses APIError which subclasses
        # DockerException — a blanket DockerException catch would call a genuinely
        # absent container "blind", which is the same category error in reverse.
        if "NotFound" in type(e).__name__ or "not found" in str(e).lower():
            return _absent_snapshot()
        if _looks_like_daemon_unreachable(str(e)):
            raise DockerObserverUnavailable(f"docker SDK cannot reach daemon: {e}") from e
        logger.warning("docker SDK inspect failed for %s: %s", name, e)
        return None


def _inspect_via_cli(name: str) -> Optional[Dict[str, Any]]:
    """Fallback: shell out to docker CLI.

    Raises :class:`DockerObserverUnavailable` when the CLI is present but the
    daemon is not reachable.
    """
    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                (
                    "{{.State.Status}}"
                    "|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}"
                    "|{{.State.StartedAt}}"
                    "|{{range $k, $v := .NetworkSettings.Networks}}{{$k}},{{end}}"
                    "|{{.HostConfig.NetworkMode}}"
                ),
                name,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        # No docker client at all — we are blind, NOT looking at an empty fleet.
        raise DockerObserverUnavailable("docker CLI not found on PATH")
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        # Two different failures share this exit code. Splitting them here is what
        # stops archie_mcp_gateway (docker CLI present, socket absent) from
        # reporting every watched container as removed.
        stderr = (result.stderr or "").strip()
        if _looks_like_daemon_unreachable(stderr):
            raise DockerObserverUnavailable(f"docker CLI cannot reach daemon: {stderr[:300]}")
        # Genuinely not found.
        return _absent_snapshot()
    parts = result.stdout.strip().split("|")
    state = parts[0] if parts else None
    health = parts[1] if len(parts) > 1 and parts[1] != "none" else None
    started = parts[2] if len(parts) > 2 else None
    # Networks render as "a,b," — split and drop the trailing empty element.
    networks = [n for n in (parts[3].split(",") if len(parts) > 3 else []) if n]
    network_mode = parts[4] if len(parts) > 4 and parts[4] else None
    return {
        "present": True,
        "state": state,
        "health": health,
        "started_at": started,
        "networks": sorted(networks),
        "network_mode": network_mode,
    }


def docker_observer_available() -> None:
    """Raise :class:`DockerObserverUnavailable` unless docker answers at all.

    A one-call pre-flight. Called once per heartbeat pass so a blind observer
    costs ONE failed subprocess instead of ten inspects plus ten ``docker events``
    forensics queries — and, more importantly, so the pass reports one clear
    "I cannot see" verdict instead of ten confident lies.
    """
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        raise DockerObserverUnavailable("docker CLI not found on PATH") from None
    except subprocess.TimeoutExpired:
        return  # slow, not blind — let the per-container path decide
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise DockerObserverUnavailable(f"docker daemon unreachable: {stderr[:300] or 'unknown error'}")


def inspect_container(name: str) -> Dict[str, Any]:
    """Return a uniform snapshot of a container's state.

    Keys: ``present`` (bool), ``state`` (str|None), ``health`` (str|None),
    ``started_at`` (str|None), ``networks`` (list[str]),
    ``network_mode`` (str|None).

    Raises :class:`DockerObserverUnavailable` when no docker client can answer.
    It never returns ``present: False`` as a substitute for "I could not look".
    """
    snap = _inspect_via_sdk(name)
    if snap is not None:
        return snap
    snap = _inspect_via_cli(name)
    if snap is not None:
        return snap
    raise DockerObserverUnavailable("no usable docker client (SDK and CLI both failed)")


def _shares_network_namespace(network_mode: Optional[str]) -> bool:
    """True when a container deliberately has no network of its own.

    ``network_mode: service:X`` in compose becomes ``container:<id>`` in the
    inspect output, and such a container legitimately reports **zero** entries
    under ``NetworkSettings.Networks`` — it borrows the target's namespace. The
    merged VPN torrent lane (qBittorrent behind gluetun) is exactly this shape,
    so treating an empty network list as a fault without this carve-out would
    page on a container that is working as designed.

    ``host`` mode is deliberately NOT listed: it reports one network entry
    (``host``), verified on this hub against archie_hub_caddy, media_plex,
    network_ntopng and network_adguard.
    """
    if not network_mode:
        return False
    return network_mode.startswith("container:") or network_mode.startswith("service:")


# ---------------------------------------------------------------------------
# Per-container health evaluation
# ---------------------------------------------------------------------------


def _blind_record(name: str, config: Dict[str, Any], detail: str) -> Dict[str, Any]:
    """The record for a container an observer could not look at.

    One helper, used by both the per-container path and the whole-pass
    short-circuit, so the two can never drift into claiming different things
    about the same blindness.

    ``present: False`` here means *unverified*, NOT *confirmed gone*. The
    distinction is carried by ``observer_blind`` and the reason string, and it
    is why this function never returns ``severity: "error"`` — that value is
    what the agent loop turns into a restart approval.
    """
    return {
        "name": name,
        "description": config.get("description"),
        "observer_blind": True,
        "present": False,
        "state": None,
        "health": None,
        "started_at": None,
        "networks": [],
        "network_mode": None,
        "tcp_probes": {},
        "http_probe": None,
        "auto_restart_safe": bool(config.get("auto_restart_safe")),
        "compose_service": config.get("compose_service", name),
        "service_class": config.get("service_class", "always-on"),
        "severity": "warning",
        "reason": (
            f"monitoring blind — docker daemon unreachable ({detail}). State of this "
            "container is UNKNOWN, which is NOT the same as absent. Do not restart."
        ),
    }


def check_container(name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate one container. Returns a structured record the job + MCP
    tool both render.

    ``severity`` rollup per container:
      * ``error``   — container absent, exited, or running with no network
      * ``warning`` — container running but port/http probe fails
      * ``info``    — all probes pass

    A BLIND observer is reported at ``warning`` with ``observer_blind: True`` and
    an explicit "state UNKNOWN" reason — never ``error``. The agent-loop restart
    path keys on ``severity == "error"``, so a blind observer structurally cannot
    file a restart approval for a container it never actually looked at.
    """
    service_class = config.get("service_class", "always-on")
    try:
        snap = inspect_container(name)
    except DockerObserverUnavailable as e:
        return _blind_record(name, config, str(e))

    result: Dict[str, Any] = {
        "name": name,
        "description": config.get("description"),
        "observer_blind": False,
        "present": False,
        "state": None,
        "health": None,
        "started_at": None,
        "networks": [],
        "network_mode": None,
        "tcp_probes": {},
        "http_probe": None,
        "auto_restart_safe": bool(config.get("auto_restart_safe")),
        "compose_service": config.get("compose_service", name),
        "service_class": service_class,
    }
    result.update(snap)

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

    # A container can be 'running', with its daemon listening and its ports
    # correctly published, while attached to NO network — making it completely
    # unreachable. Twice on this hub: archie_tailscale (23 days) and media_samba
    # (~25 days, healthcheck FailingStreak 3014). 'running' is what made both
    # invisible, so state alone is not evidence of reachability.
    #
    # Checked BEFORE the probes deliberately: the probes can be unreliable for
    # their own reasons (host->own-published-port hairpin is broken under
    # userland-proxy=false), and "attached to no network" is a structural fault
    # that deserves its own unambiguous reason string rather than being reported
    # as a generic probe failure.
    if not snap.get("networks") and not _shares_network_namespace(snap.get("network_mode")):
        result["severity"] = "error"
        result["reason"] = (
            "container is running but attached to NO network "
            f"(network_mode={snap.get('network_mode')!r}) — unreachable regardless "
            "of process state. Recreate it from its captured config."
        )
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
        if service_class == "on-demand":
            # On-demand containers start/stop with workload — port unreachable
            # while container is running just means it's mid-lifecycle (starting
            # up or winding down). Dispatcher (media_generation_worker) manages
            # recovery. Suppress to info so V.I.G.I.L. doesn't flood Telegram.
            result["severity"] = "info"
            result["reason"] = f"on-demand: {', '.join(failed)} (dispatcher manages start/stop)"
        else:
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

    ``observer_blind`` is the load-bearing top-level field. When True, NOTHING in
    this payload is evidence about any container: ``down_names`` is empty by
    construction, because a check that could not see is not allowed to claim
    absence. Consumers must treat a blind pass as "the monitor is broken", never
    as "the fleet is healthy" — see :class:`DockerObserverUnavailable`.
    """
    ran_at = datetime.now(timezone.utc).isoformat()

    # Pre-flight: one call decides whether the rest of the pass can mean anything.
    # Blind is the common case for in-process MCP lanes, and it used to be
    # indistinguishable from a total outage.
    try:
        docker_observer_available()
    except DockerObserverUnavailable as e:
        detail = str(e)
        logger.error("[infra_heartbeat] observer blind, pass is inconclusive: %s", detail)
        # Build the records directly. Calling check_container() here would work,
        # but it would re-attempt the daemon for EVERY entry — 1 + 2N failed
        # subprocesses instead of 1, to rediscover a fact the pre-flight just
        # established. The pre-flight exists to be a short circuit.
        per_container = [_blind_record(name, config, detail) for name, config in CRITICAL_CONTAINERS.items()]
        return {
            "ran_at": ran_at,
            "checked_count": len(CRITICAL_CONTAINERS),
            "containers": per_container,
            # Deliberately empty. Blindness is not absence.
            "down_names": [],
            "warning_names": list(CRITICAL_CONTAINERS),
            "severity": "warning",
            "observer_blind": True,
            "reasons": [
                f"MONITORING BLIND — docker unreachable from this process ({detail}). "
                f"All {len(CRITICAL_CONTAINERS)} watched containers are UNKNOWN; "
                "no container has been found absent. The scheduled job runs where "
                "docker IS reachable — check that before trusting any alarm."
            ],
            "summary_metrics": {
                "total": len(CRITICAL_CONTAINERS),
                "down": 0,
                "warnings": 0,
                "healthy": 0,
                "blind": len(CRITICAL_CONTAINERS),
            },
        }

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
        "observer_blind": False,
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

    Accepts either a container name (the registry key) or a compose service
    name, because both are what callers actually have: the agent loop files
    ``compose_service`` from the record, while a human approving from Telegram
    sees the container name.

    The ``-f`` flag is the point of this rewrite. Six of the ten original
    entries name a service that does not exist in /mnt/archie_brain's compose
    file, so every one of their restarts failed with "no such service" —
    an approval spent and a container never brought back. Each entry now
    carries the compose file it belongs to, and this resolves it here.
    """
    entry = None
    entry_name = None
    for key, cfg in CRITICAL_CONTAINERS.items():
        if compose_service in (key, cfg.get("compose_service", key)):
            entry, entry_name = cfg, key
            break
    if entry is None:
        return {
            "success": False,
            "error": f"{compose_service!r} is not in the critical container registry",
        }

    service = entry.get("compose_service", entry_name)
    compose_file = entry.get("compose_file")

    # Refuse rather than guess. Falling back to a cwd-only compose invocation
    # is exactly the bug this replaced: it silently targets the wrong stack, or
    # errors "no such service" after a human has approved a restart.
    if not compose_file:
        return {
            "success": False,
            "error": (
                f"{entry_name!r} has no compose_file in the registry — it is "
                "detection-only and cannot be restarted automatically. "
                "Recover it manually."
            ),
        }
    if not os.path.exists(compose_file):
        return {
            "success": False,
            "error": f"compose file {compose_file!r} for {entry_name!r} does not exist on this host",
        }

    cmd = ["docker", "compose", "-f", compose_file, "up", "-d", "--no-deps", service]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=90,
            cwd=os.path.dirname(compose_file) or "/mnt/archie_brain",
        )
    except Exception as e:
        logger.error("restart_container(%s) subprocess failed: %s", compose_service, e)
        return {"success": False, "error": str(e)}
    if result.returncode != 0:
        return {
            "success": False,
            "error": f"docker compose exit {result.returncode}: {result.stderr.strip()[:300]}",
            "stdout": result.stdout.strip()[:300],
            "command": " ".join(cmd),
        }
    logger.info("[infra_heartbeat] Restarted %s via %s: %s", entry_name, compose_file, reason)
    return {
        "success": True,
        "container": entry_name,
        "compose_service": service,
        "compose_file": compose_file,
        "reason": reason,
        "stdout": result.stdout.strip()[:300],
    }


# ---------------------------------------------------------------------------
# Alert formatter
# ---------------------------------------------------------------------------


def format_alert_message(result: Dict[str, Any]) -> str:
    """Compact message for Telegram / system_notifications."""
    metrics = result["summary_metrics"]

    # Blindness gets its own rendering. Folding it into the normal header would
    # print "0 down · 0 warning · 0 healthy" — which reads as a healthy fleet and
    # is exactly the misreading that turns a broken monitor into a false all-clear.
    if result.get("observer_blind"):
        return "\n".join(
            [
                "V.I.G.I.L. — infra heartbeat",
                "Severity: *WARNING* — ⚠️ *MONITORING BLIND* · "
                f"{metrics.get('blind', 0)} unverified ({metrics['total']} watched)",
                "",
                "This process cannot reach the docker daemon, so it could not inspect "
                "anything. Every watched container is UNKNOWN.",
                "",
                "**This is NOT a report of missing containers.**",
                *(f"• {r}" for r in result.get("reasons", [])),
                "",
                "Check the hub's docker socket before trusting any alarm.",
            ]
        )

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
